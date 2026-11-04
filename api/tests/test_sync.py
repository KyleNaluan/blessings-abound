"""Publishing to the mock channels and keeping them in step after a sale, end to end.

The app, both channels and their webhooks all run in the test process against real Postgres, with
the model and the eBay search stubbed by the client fixture from test_appraisal.
"""

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlmodel import Session, col, select, update

from app import publish_to_channels
from app.channels import ListingContent, get_channels
from app.db import get_session, get_session_factory
from app.main import app
from app.models import (
    ChannelName,
    ConflictKind,
    Item,
    ItemStatus,
    Job,
    JobKind,
    JobStatus,
    Listing,
    ListingStatus,
    SaleEvent,
    SaleSource,
    SyncEvent,
    SyncLogEntry,
)
from app.sync import MAX_ATTEMPTS, poll_channel, retry_delay, run_jobs, utc_now
from mock_channel.service import sign
from tests.channel_harness import KEYS, Market, request_sessions
from tests.test_appraisal import (  # noqa: F401, the fixtures these tests build on
    MANAGER_TOKEN,
    appraised_item,
    as_token,
    client,
    decide,
    model_replies,
    storage,
)

A, B = ChannelName.CHANNEL_A, ChannelName.CHANNEL_B


@pytest.fixture
def market(client: TestClient, connection: Connection) -> Iterator[Market]:  # noqa: F811
    market = Market(connection, webhook_client=client)
    app.dependency_overrides[get_channels] = lambda: dict(market.adapters)
    app.dependency_overrides[get_session_factory] = lambda: market.factory
    app.dependency_overrides[get_session] = request_sessions(market.factory)
    yield market
    market.close()


def approved_item(client: TestClient) -> str:  # noqa: F811
    item_id, appraisal_id = appraised_item(client)
    assert decide(client, item_id, appraisal_id).status_code == 201
    return item_id


def publish(client: TestClient, item_id: str, **body: Any) -> Any:  # noqa: F811
    return client.post(f"/items/{item_id}/listings", json=body, headers=as_token(MANAGER_TOKEN))


def listed_item(client: TestClient) -> tuple[str, dict[ChannelName, dict[str, Any]]]:  # noqa: F811
    item_id = approved_item(client)
    response = publish(client, item_id)
    assert response.status_code == 200, response.text
    listings = {ChannelName(row["channel"]): row for row in response.json()}
    assert {row["status"] for row in listings.values()} == {"active"}
    return item_id, listings


def item_status(session: Session, item_id: str) -> ItemStatus:
    session.expire_all()
    return session.get_one(Item, UUID(item_id)).status


def listing_status(session: Session, listing: dict[str, Any]) -> ListingStatus:
    session.expire_all()
    return session.get_one(Listing, UUID(listing["id"])).status


def events(session: Session, item_id: str) -> list[SyncEvent]:
    """The item's sync log, sorted, because now() is the same all through a test's transaction."""
    session.expire_all()
    rows = session.exec(select(SyncLogEntry).where(SyncLogEntry.item_id == UUID(item_id)))
    return sorted(row.event for row in rows)


def flags(session: Session, conflict: ConflictKind | None = None) -> list[SyncLogEntry]:
    session.expire_all()
    query = select(SyncLogEntry).where(SyncLogEntry.event == SyncEvent.FLAGGED)
    if conflict is not None:
        query = query.where(SyncLogEntry.conflict == conflict)
    return list(session.exec(query))


def pending_jobs(session: Session) -> list[Job]:
    session.expire_all()
    return list(session.exec(select(Job).where(Job.status == JobStatus.PENDING)))


def test_publish_lists_the_item_on_both_channels(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)

    assert item_status(session, item_id) == ItemStatus.LISTED
    for channel, listing in listings.items():
        remote = market.listing(channel, listing["channel_listing_id"])
        # The channel keeps the app's listing id, which makes a repeated publish return one listing.
        assert remote["external_ref"] == listing["id"]
        assert remote["status"] == "active"
        assert remote["price_cents"] == listing["price_cents"]
        assert remote["title"] == "Carhartt canvas jacket"
        assert remote["brand"] == "Carhartt"
    assert events(session, item_id) == [SyncEvent.PUBLISHED, SyncEvent.PUBLISHED]
    assert client.get(f"/items/{item_id}/listings").json() == list(listings.values())


def test_publishing_again_makes_no_second_listing(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)

    again = publish(client, item_id)

    assert again.status_code == 200, again.text
    assert [row["id"] for row in again.json()] == [listing["id"] for listing in listings.values()]
    for channel in (A, B):
        assert len(market.adapters[channel].active_listings()) == 1


def test_only_a_manager_can_publish(client: TestClient, market: Market) -> None:  # noqa: F811
    item_id = approved_item(client)

    response = client.post(f"/items/{item_id}/listings", json={})

    assert response.status_code == 403


def test_an_item_without_a_yes_decision_cannot_be_published(
    client: TestClient,  # noqa: F811
    market: Market,
) -> None:
    item_id, appraisal_id = appraised_item(client)
    assert publish(client, item_id).status_code == 409

    decide(client, item_id, appraisal_id, "no")
    response = publish(client, item_id)

    assert response.status_code == 409
    assert response.json()["detail"] == "An item that is declined can't be listed."


def test_the_manager_can_set_the_price_and_the_channels(
    client: TestClient,  # noqa: F811
    market: Market,
) -> None:
    item_id = approved_item(client)

    response = publish(client, item_id, channels=["channel_b"], price_cents=4500)

    assert response.status_code == 200, response.text
    [listing] = response.json()
    assert listing["channel"] == "channel_b"
    assert listing["price_cents"] == 4500
    assert market.adapters[A].active_listings() == []


def test_channel_b_refuses_electronics_and_channel_a_lists_them(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    model_replies(
        category="electronics_games",
        brand="Nintendo",
        product="Switch console",
        search_query="Nintendo Switch console",
        color=None,
        material=None,
    )
    item_id = approved_item(client)

    response = publish(client, item_id)

    assert response.status_code == 200, response.text
    listings = {row["channel"]: row for row in response.json()}
    assert listings["channel_a"]["status"] == "active"
    assert listings["channel_b"]["status"] == "rejected"
    assert listings["channel_b"]["status_detail"] == (
        "Channel B refused it: Channel B takes clothing only."
    )
    assert item_status(session, item_id) == ItemStatus.LISTED
    assert SyncEvent.PUBLISH_REJECTED in events(session, item_id)
    # A refusal is final, so nothing is left to retry.
    assert pending_jobs(session) == []


def test_a_sale_on_one_channel_takes_the_item_down_from_the_other(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)

    order = market.buy(A, listings[A]["channel_listing_id"])

    assert item_status(session, item_id) == ItemStatus.SOLD
    assert listing_status(session, listings[A]) == ListingStatus.SOLD
    assert listing_status(session, listings[B]) == ListingStatus.ENDED
    assert market.listing(B, listings[B]["channel_listing_id"])["status"] == "ended"
    assert "Carhartt" not in market.shops[B].get("/").text
    [sale] = session.exec(select(SaleEvent)).all()
    assert (sale.channel, sale.channel_order_id, sale.source) == (
        A,
        order["id"],
        SaleSource.WEBHOOK,
    )
    assert sale.price_cents == listings[A]["price_cents"]
    # The webhook was answered, so polling finds nothing more to record.
    assert market.adapters[A].unacknowledged_orders() == []
    assert events(session, item_id) == sorted(
        [SyncEvent.PUBLISHED, SyncEvent.PUBLISHED, SyncEvent.SALE_RECORDED, SyncEvent.DELISTED]
    )
    assert pending_jobs(session) == []


def test_polling_finds_a_sale_whose_webhook_never_arrived(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)

    order = market.buy(B, listings[B]["channel_listing_id"], send_webhook=False)
    assert item_status(session, item_id) == ItemStatus.LISTED

    result = poll_channel(session, market.adapters[B])
    run_jobs(session, dict(market.adapters))

    assert result.orders == 1
    assert item_status(session, item_id) == ItemStatus.SOLD
    [sale] = session.exec(select(SaleEvent)).all()
    assert (sale.channel_order_id, sale.source) == (order["id"], SaleSource.POLLING)
    assert market.listing(A, listings[A]["channel_listing_id"])["status"] == "ended"
    assert poll_channel(session, market.adapters[B]).orders == 0


def test_polling_finds_a_sale_whose_webhook_failed(
    client: TestClient,  # noqa: F811
    connection: Connection,
    session: Session,
) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("The app is down.", request=request)

    market = Market(
        connection, webhook_client=httpx2.Client(transport=httpx2.MockTransport(refuse))
    )
    try:
        app.dependency_overrides[get_channels] = lambda: dict(market.adapters)
        app.dependency_overrides[get_session_factory] = lambda: market.factory
        app.dependency_overrides[get_session] = request_sessions(market.factory)
        item_id, listings = listed_item(client)

        market.buy(A, listings[A]["channel_listing_id"])
        assert item_status(session, item_id) == ItemStatus.LISTED

        assert poll_channel(session, market.adapters[A]).orders == 1
        assert item_status(session, item_id) == ItemStatus.SOLD
    finally:
        market.close()


def test_a_failed_delist_is_retried_from_the_jobs_table(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)
    market.set_offline(B)

    market.buy(A, listings[A]["channel_listing_id"])

    assert item_status(session, item_id) == ItemStatus.SOLD
    assert listing_status(session, listings[B]) == ListingStatus.ACTIVE
    [job] = pending_jobs(session)
    assert job.attempts == 1
    assert job.last_error == "Channel B answered 503: Channel B is offline."
    assert SyncEvent.DELIST_FAILED in events(session, item_id)

    # Not due yet, so nothing runs until the wait has passed.
    now = utc_now()
    assert run_jobs(session, dict(market.adapters), now) == 0
    market.set_offline(B, False)
    assert run_jobs(session, dict(market.adapters), now + retry_delay(1)) == 1

    assert listing_status(session, listings[B]) == ListingStatus.ENDED
    assert market.listing(B, listings[B]["channel_listing_id"])["status"] == "ended"
    assert pending_jobs(session) == []


def test_a_delist_that_gives_up_is_found_by_polling_as_a_stale_listing(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)
    market.set_offline(B)
    market.buy(A, listings[A]["channel_listing_id"])
    now = utc_now()
    for attempt in range(1, MAX_ATTEMPTS):
        now += retry_delay(attempt)
        assert run_jobs(session, dict(market.adapters), now) == 1
    session.expire_all()
    [job] = session.exec(select(Job).where(Job.kind == JobKind.END_LISTING)).all()
    assert job.status == JobStatus.FAILED
    assert job.attempts == MAX_ATTEMPTS
    assert SyncEvent.DELIST_GAVE_UP in events(session, item_id)

    market.set_offline(B, False)
    assert poll_channel(session, market.adapters[B], now).flags == 1
    # Polling again while the retry is due raises no second flag.
    assert poll_channel(session, market.adapters[B], now).flags == 0
    [stale] = flags(session, ConflictKind.STALE_LISTING)
    assert stale.item_id == UUID(item_id)
    assert stale.channel == B
    assert stale.channel_listing_id == listings[B]["channel_listing_id"]
    assert stale.detail["taking_down"] is True
    assert stale.resolved_at is None

    run_jobs(session, dict(market.adapters), now)

    assert market.listing(B, listings[B]["channel_listing_id"])["status"] == "ended"
    [stale] = flags(session, ConflictKind.STALE_LISTING)
    assert stale.resolved_at is not None
    assert stale.resolution == "Turnstone took the listing down."


def test_a_double_sale_of_the_same_item_is_flagged(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)
    # The first sale's webhook is lost, so the app doesn't know to take the item down from B.
    first = market.buy(A, listings[A]["channel_listing_id"], send_webhook=False)

    # The second sale's webhook arrives, and taking the item down from A finds A already sold.
    second = market.buy(B, listings[B]["channel_listing_id"])

    assert item_status(session, item_id) == ItemStatus.SOLD
    assert {sale.channel_order_id for sale in session.exec(select(SaleEvent))} == {
        first["id"],
        second["id"],
    }
    [double] = flags(session, ConflictKind.DOUBLE_SALE)
    assert double.item_id == UUID(item_id)
    assert (double.channel, double.channel_order_id) == (A, first["id"])
    assert double.source == SaleSource.POLLING
    assert double.resolved_at is None
    assert [order["channel_order_id"] for order in double.detail["other_orders"]] == [second["id"]]
    assert double.message == (
        "Carhartt canvas jacket sold on Channel B and again on Channel A, so one of the orders "
        "needs cancelling."
    )
    assert SyncEvent.DELIST_FOUND_SOLD in events(session, item_id)
    assert listing_status(session, listings[A]) == ListingStatus.SOLD
    assert listing_status(session, listings[B]) == ListingStatus.SOLD
    # Polling and webhooks seeing the same orders again raise nothing new.
    for channel in (A, B):
        poll_channel(session, market.adapters[channel])
    assert len(flags(session)) == 1


def test_a_double_sale_reported_by_two_webhooks_is_flagged(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)
    market.set_offline(B)
    market.buy(A, listings[A]["channel_listing_id"])
    market.set_offline(B, False)

    # B sold before its end job came round again.
    second = market.buy(B, listings[B]["channel_listing_id"])

    [double] = flags(session, ConflictKind.DOUBLE_SALE)
    assert (double.channel, double.channel_order_id) == (B, second["id"])
    assert double.source == SaleSource.WEBHOOK
    run_jobs(session, dict(market.adapters), utc_now() + timedelta(minutes=10))
    assert pending_jobs(session) == []
    assert item_status(session, item_id) == ItemStatus.SOLD


def webhook(client: TestClient, channel: ChannelName, body: bytes, key: str | None = None) -> Any:  # noqa: F811
    return client.post(
        f"/channels/{channel.value}/sales",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Channel-Signature": sign(key or KEYS[channel], body),
        },
    )


def order_body(listing: dict[str, Any], order_id: str | None = None) -> bytes:
    return json.dumps(
        {
            "id": order_id or str(uuid4()),
            "listing_id": listing["channel_listing_id"],
            "external_ref": listing["id"],
            "price_cents": listing["price_cents"],
            "sold_at": utc_now().isoformat(),
        }
    ).encode()


def test_a_repeated_webhook_records_the_sale_once(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)
    body = order_body(listings[A])

    assert webhook(client, A, body).status_code == 204
    assert webhook(client, A, body).status_code == 204

    assert len(session.exec(select(SaleEvent)).all()) == 1
    assert events(session, item_id).count(SyncEvent.SALE_RECORDED) == 1
    assert flags(session) == []


def test_a_webhook_with_a_wrong_signature_is_refused(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client)

    response = webhook(client, A, order_body(listings[A]), key="not-the-key")
    unsigned = client.post("/channels/channel_a/sales", content=order_body(listings[A]))

    assert response.status_code == 401
    assert unsigned.status_code == 401
    assert item_status(session, item_id) == ItemStatus.LISTED


def test_a_webhook_that_cannot_be_read_is_refused(
    client: TestClient,  # noqa: F811
    market: Market,
) -> None:
    response = webhook(client, A, b'{"id": "missing everything else"}')

    assert response.status_code == 422


def test_a_webhook_for_a_channel_not_set_up_is_not_found(
    client: TestClient,  # noqa: F811
    market: Market,
) -> None:
    app.dependency_overrides[get_channels] = lambda: {A: market.adapters[A]}

    response = webhook(client, B, b"{}")

    assert response.status_code == 404


def test_listings_and_sales_turnstone_has_no_record_of_are_flagged(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    content = ListingContent(
        title="Listed by hand",
        description="Someone listed this on the channel directly.",
        category="apparel",
        condition="pre_owned",
        price_cents=1200,
        brand="Levi's",
    )
    stranger = market.adapters[A].publish(uuid4(), content)

    assert poll_channel(session, market.adapters[A]).flags == 1
    assert poll_channel(session, market.adapters[A]).flags == 0
    order = market.buy(A, stranger.id)

    unknown = flags(session, ConflictKind.UNKNOWN_LISTING)
    assert len(unknown) == 2
    sale_flag = next(row for row in unknown if row.channel_order_id is not None)
    assert sale_flag.channel_order_id == order["id"]
    assert sale_flag.item_id is None
    assert session.exec(select(SaleEvent)).all() == []
    # The order was answered, so it isn't raised again on the next poll.
    assert market.adapters[A].unacknowledged_orders() == []


def test_a_publish_to_an_offline_channel_is_retried(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    market.set_offline(B)
    item_id = approved_item(client)

    response = publish(client, item_id)

    listings = {ChannelName(row["channel"]): row for row in response.json()}
    assert listings[A]["status"] == "active"
    assert listings[B]["status"] == "pending"
    assert item_status(session, item_id) == ItemStatus.LISTED
    market.set_offline(B, False)
    run_jobs(session, dict(market.adapters), utc_now() + retry_delay(1))
    assert listing_status(session, listings[B]) == ListingStatus.ACTIVE
    assert len(market.adapters[B].active_listings()) == 1


def test_an_item_that_sells_before_a_publish_lands_is_not_listed_there(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    market.set_offline(B)
    item_id = approved_item(client)
    listings = {ChannelName(row["channel"]): row for row in publish(client, item_id).json()}
    market.buy(A, listings[A]["channel_listing_id"])
    market.set_offline(B, False)

    run_jobs(session, dict(market.adapters), utc_now() + timedelta(minutes=10))

    assert listing_status(session, listings[B]) == ListingStatus.ENDED
    assert SyncEvent.PUBLISH_SKIPPED in events(session, item_id)
    assert market.adapters[B].active_listings() == []
    assert pending_jobs(session) == []


def test_a_publish_that_gives_up_marks_the_listing_failed(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    market.set_offline(B)
    item_id = approved_item(client)
    listings = {ChannelName(row["channel"]): row for row in publish(client, item_id).json()}
    now = utc_now()
    for attempt in range(1, MAX_ATTEMPTS):
        now += retry_delay(attempt)
        run_jobs(session, dict(market.adapters), now)

    assert listing_status(session, listings[B]) == ListingStatus.FAILED
    assert SyncEvent.PUBLISH_GAVE_UP in events(session, item_id)

    # Publishing again tries the failed channel once more.
    market.set_offline(B, False)
    again = {row["channel"]: row for row in publish(client, item_id).json()}
    assert again["channel_b"]["status"] == "active"
    assert again["channel_b"]["id"] == listings[B]["id"]


def test_retries_wait_longer_each_time_up_to_five_minutes() -> None:
    assert [retry_delay(n).total_seconds() for n in range(1, 9)] == [
        5,
        10,
        20,
        40,
        80,
        160,
        300,
        300,
    ]


def test_the_script_publishes_the_newest_item_staff_said_yes_to(
    client: TestClient,  # noqa: F811
    market: Market,
    session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    older = approved_item(client)
    newest = approved_item(client)
    # Both were made in one transaction, where now() doesn't move.
    hour_ago = utc_now() - timedelta(hours=1)
    session.exec(
        update(Item)
        .where(col(Item.id) == UUID(older))
        .values(created_at=hour_ago, updated_at=hour_ago)
    )

    with market.factory() as script_session:
        code = publish_to_channels.publish(script_session, dict(market.adapters), ["manager1"])

    assert code == 0
    assert capsys.readouterr().out == (
        f"Item {newest}:\n  Channel A: active\n  Channel B: active\n"
    )
    assert item_status(session, newest) == ItemStatus.LISTED


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["staff1"], "staff1 isn't an active manager."),
        (["nobody"], "nobody isn't an active manager."),
        (["manager1"], "No appraised item has a yes decision yet."),
        (["manager1", str(uuid4())], "That item doesn't exist."),
    ],
)
def test_the_script_refuses_what_the_route_refuses(
    client: TestClient,  # noqa: F811
    market: Market,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    message: str,
) -> None:
    with market.factory() as script_session:
        code = publish_to_channels.publish(script_session, dict(market.adapters), arguments)

    assert code == 1
    assert capsys.readouterr().err.strip() == message
