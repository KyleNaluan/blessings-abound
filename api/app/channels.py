"""The adapter interface the app uses to reach a sales channel, and the one for the mock channels.

Everything else in the app talks to a channel through `ChannelAdapter`, so a real platform could
replace a mock one with a new adapter and no other change. The mock channels are separate services,
in mock_channel/, reached over HTTP with a per-channel key.
"""

import hashlib
import hmac
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol
from uuid import UUID

import httpx2
from fastapi import status
from pydantic import BaseModel, ValidationError

from app.models import ChannelName
from app.settings import get_settings

LABELS = {ChannelName.CHANNEL_A: "Channel A", ChannelName.CHANNEL_B: "Channel B"}
TIMEOUT_SECONDS = 10.0


class ListingContent(BaseModel):
    """What one channel shows for an item. #19 drafts the words and #42 sets the price."""

    title: str
    description: str
    category: str
    condition: str
    price_cents: int
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    specifics: dict[str, str] = {}


class ChannelListing(BaseModel):
    id: str
    # The id the app sent with the listing, which is the app's own listings.id.
    external_ref: str
    status: str
    price_cents: int


class ChannelOrder(BaseModel):
    id: str
    listing_id: str
    external_ref: str
    price_cents: int
    sold_at: datetime


class ChannelError(Exception):
    """Something the channel said or failed to say, with a message fit for the sync log."""


class ChannelUnavailableError(ChannelError):
    """The channel could not be reached or had a fault, so the same call can be tried again."""


class ChannelRejectedError(ChannelError):
    """The channel refused the request as it stands, so trying again would get the same answer."""


class ListingAlreadySoldError(ChannelRejectedError):
    """The listing sold on the channel before it could be ended."""


class ListingNotFoundError(ChannelRejectedError):
    """The channel has no listing with that id."""


class ChannelAdapter(Protocol):
    name: ChannelName

    def publish(self, external_ref: UUID, content: ListingContent) -> ChannelListing:
        """Create the listing, or return the one already made for this external_ref."""
        ...

    def end_listing(self, channel_listing_id: str) -> None:
        """Take the listing down. Ending one twice is fine, and a sold one raises."""
        ...

    def active_listings(self) -> list[ChannelListing]: ...

    def unacknowledged_orders(self) -> list[ChannelOrder]:
        """Orders the app hasn't confirmed it has, which is what polling checks."""
        ...

    def acknowledge_order(self, order_id: str) -> None: ...

    def verify_signature(self, body: bytes, signature: str | None) -> bool:
        """Whether a sale webhook really came from this channel."""
        ...

    def parse_webhook(self, body: bytes) -> ChannelOrder:
        """The order in a sale webhook whose signature has been checked."""
        ...


class MockChannelAdapter:
    """Reaches one mock channel's seller API over HTTP."""

    def __init__(self, name: ChannelName, client: httpx2.Client, key: str) -> None:
        self.name = name
        self.client = client
        self.key = key
        self.label = LABELS[name]

    @classmethod
    def connect(
        cls, name: ChannelName, url: str, key: str, transport: httpx2.BaseTransport | None = None
    ) -> "MockChannelAdapter":
        client = httpx2.Client(
            base_url=f"{url.rstrip('/')}/api",
            headers={"Authorization": f"Bearer {key}"},
            transport=transport,
            timeout=TIMEOUT_SECONDS,
        )
        return cls(name, client, key)

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx2.HTTPError as error:
            raise ChannelUnavailableError(f"{self.label} couldn't be reached.") from error
        if response.status_code == status.HTTP_404_NOT_FOUND:
            raise ListingNotFoundError(f"{self.label} has no such listing or order.")
        if response.status_code == status.HTTP_409_CONFLICT:
            raise ListingAlreadySoldError(f"{self.label} says {_detail(response)}")
        if response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ):
            raise ChannelRejectedError(f"{self.label} refused it: {_detail(response)}")
        if not response.is_success:
            # Includes 401, because a wrong key is fixed in settings and the call then succeeds.
            raise ChannelUnavailableError(
                f"{self.label} answered {response.status_code}: {_detail(response)}"
            )
        return response

    def _parse[T: BaseModel](self, model: type[T], data: Any) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            raise ChannelUnavailableError(f"{self.label} sent an answer we can't read.") from error

    def publish(self, external_ref: UUID, content: ListingContent) -> ChannelListing:
        body = {"external_ref": str(external_ref), **content.model_dump()}
        response = self._call("POST", "/listings", json=body)
        return self._parse(ChannelListing, response.json())

    def end_listing(self, channel_listing_id: str) -> None:
        self._call("POST", f"/listings/{channel_listing_id}/end")

    def active_listings(self) -> list[ChannelListing]:
        response = self._call("GET", "/listings", params={"status": "active"})
        return [self._parse(ChannelListing, row) for row in response.json()]

    def unacknowledged_orders(self) -> list[ChannelOrder]:
        response = self._call("GET", "/orders", params={"acknowledged": "false"})
        return [self._parse(ChannelOrder, row) for row in response.json()]

    def acknowledge_order(self, order_id: str) -> None:
        self._call("POST", f"/orders/{order_id}/acknowledge")

    def verify_signature(self, body: bytes, signature: str | None) -> bool:
        expected = "sha256=" + hmac.new(self.key.encode(), body, hashlib.sha256).hexdigest()
        return signature is not None and hmac.compare_digest(signature, expected)

    def parse_webhook(self, body: bytes) -> ChannelOrder:
        try:
            return ChannelOrder.model_validate_json(body)
        except ValidationError as error:
            raise ChannelRejectedError(f"{self.label} sent a sale we can't read.") from error


def _detail(response: httpx2.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail if isinstance(detail, str) else response.reason_phrase


Channels = dict[ChannelName, ChannelAdapter]


@lru_cache
def _configured_channels() -> tuple[ChannelAdapter, ...]:
    settings = get_settings()
    configured = {
        ChannelName.CHANNEL_A: (settings.channel_a_url, settings.channel_a_key),
        ChannelName.CHANNEL_B: (settings.channel_b_url, settings.channel_b_key),
    }
    return tuple(
        MockChannelAdapter.connect(name, url, key)
        for name, (url, key) in configured.items()
        if url and key
    )


def get_channels() -> Channels:
    """The channels set up on this server, which may be none."""
    return {adapter.name: adapter for adapter in _configured_channels()}
