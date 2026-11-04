"""Both mock channels running in the test process on the test's rolled-back connection.

Each channel is its real FastAPI app behind a TestClient, so the app's adapter, the channel's
seller API, its storefront and its sale webhook all run as they do in docker compose.
"""

from collections.abc import Callable, Iterator
from typing import Any

import httpx2
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlmodel import Session

from app.channels import MockChannelAdapter
from app.models import ChannelName
from mock_channel import channel_a, channel_b, service
from mock_channel.service import ChannelSettings

KEYS = {ChannelName.CHANNEL_A: "test-key-a", ChannelName.CHANNEL_B: "test-key-b"}
APPS: dict[ChannelName, FastAPI] = {
    ChannelName.CHANNEL_A: channel_a.app,
    ChannelName.CHANNEL_B: channel_b.app,
}


def session_factory(connection: Connection) -> Callable[[], Session]:
    return lambda: Session(bind=connection, join_transaction_mode="create_savepoint")


def request_sessions(factory: Callable[[], Session]) -> Callable[[], Iterator[Session]]:
    """A session per request, as in production.

    A request can now be inside another, such as a channel's webhook arriving while the purchase
    that sent it is still open, so each needs its own savepoint, released in order.
    """

    def get_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    return get_session


class Market:
    """The two channels, a shopper on each storefront, and the app's adapter for each."""

    def __init__(self, connection: Connection, webhook_client: httpx2.Client | None) -> None:
        self.factory = session_factory(connection)
        self.shops: dict[ChannelName, TestClient] = {}
        self.adapters: dict[ChannelName, MockChannelAdapter] = {}
        for name, app in APPS.items():
            settings = ChannelSettings(
                key=KEYS[name],
                webhook_url=f"http://testserver/channels/{name.value}/sales"
                if webhook_client
                else None,
            )
            app.dependency_overrides[service.get_session_factory] = lambda: self.factory
            app.dependency_overrides[service.get_channel_settings] = lambda s=settings: s
            if webhook_client is not None:
                app.dependency_overrides[service.get_webhook_client] = lambda: webhook_client
            self.shops[name] = TestClient(app, base_url=f"http://{name.value}.test")
            seller = TestClient(
                app,
                base_url=f"http://{name.value}.test/api",
                headers={"Authorization": f"Bearer {KEYS[name]}"},
            )
            self.adapters[name] = MockChannelAdapter(name, seller, KEYS[name])

    def close(self) -> None:
        for app in APPS.values():
            app.dependency_overrides.clear()

    def buy(self, channel: ChannelName, listing_id: str, *, send_webhook: bool = True) -> Any:
        response = self.shops[channel].post(
            "/purchases", json={"listing_id": listing_id, "send_webhook": send_webhook}
        )
        assert response.status_code == 201, response.text
        return response.json()

    def set_offline(self, channel: ChannelName, offline: bool = True) -> None:
        response = self.shops[channel].post(
            "/admin/offline",
            data={"offline": "true" if offline else "false"},
            auth=("demo", KEYS[channel]),
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text

    def listing(self, channel: ChannelName, channel_listing_id: str) -> dict[str, Any]:
        response = self.adapters[channel].client.get(f"/listings/{channel_listing_id}")
        assert response.status_code == 200, response.text
        return response.json()
