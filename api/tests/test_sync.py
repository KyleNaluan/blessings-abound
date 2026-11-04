"""Publishing to the mock channels and keeping them in step after a sale, end to end.

The app, both channels and their webhooks all run in the test process against real Postgres, with
the models and the eBay search stubbed by the client fixture from test_approval. An item reaches
the channels the way it does in the app: staff send the drafts on, a manager approves the item and
gives it a shelf, and the scheduler's job run, done here by hand, puts it up.
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
from sqlmodel import Session, select

from app.channels import ListingContent, get_channels
from app.db import get_session, get_session_factory
from app.jobs import MAX_ATTEMPTS, utc_now
from app.main import app
from app.models import (
    Channel,
    ConflictKind,
    Item,
    ItemCard,
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
from app.sync import poll_channel, retry_delay, run_jobs
from mock_channel.service import sign
from tests.channel_harness import KEYS, Market, request_sessions
from tests.test_appraisal import appraised_item, decide, draft_reply, model_replies, use_drafter
from tests.test_approval import (  # noqa: F401, the fixtures these tests build on
    approve,
    client,
    item_row,
    manager,
    review,
    sent_item,
    store,
)

A, B = Channel.CHANNEL_A, Channel.CHANNEL_B
SHELF = {"location_code": "A3"}


@pytest.fixture
def market(client: TestClient, connection: Connection) -> Iterator[Market]:  # noqa: F811
    market = Market(connection, webhook_client=client)
    app.dependency_overrides[get_channels] = lambda: dict(market.adapters)
    app.dependency_overrides[get_session_factory] = lambda: market.factory
    app.dependency_overrides[get_session] = request_sessions(market.factory)
    yield market
    market.close()


def approved_item(client: TestClient, manager: TestClient) -> str:  # noqa: F811
    """Sent on by staff with a draft for each channel, packaged and approved, with no shelf yet."""
    item_id = sent_item(client)
    assert store(manager, item_id).status_code == 200
    response = approve(manager, item_id)
    assert response.status_code == 200, response.text
    return item_id


def stored_item(client: TestClient, manager: TestClient) -> str:  # noqa: F811
    """Approved and on a shelf, which queues a publish job for each channel."""
    item_id = approved_item(client, manager)
    response = store(manager, item_id, **SHELF)
    assert response.status_code == 200, response.text
    return item_id


def item_listings(manager: TestClient, item_id: str) -> dict[Channel, dict[str, Any]]:  # noqa: F811
    response = manager.get(f"/items/{item_id}/listings")
    assert response.status_code == 200, response.text
    return {Channel(row["channel"]): row for row in response.json()}


def run_scheduler(session: Session, market: Market) -> None:
    """What the scheduler thread does every few seconds."""
    run_jobs(session, dict(market.adapters))


def listed_item(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
    market: Market,
) -> tuple[str, dict[Channel, dict[str, Any]]]:
    item_id = stored_item(client, manager)
    run_scheduler(session, market)
    listings = item_listings(manager, item_id)
    assert {row["status"] for row in listings.values()} == {"active"}
    return item_id, listings


def publish(manager: TestClient, item_id: str) -> Any:  # noqa: F811
    return manager.post(f"/items/{item_id}/listings")


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


def test_storing_an_approved_item_lists_it_on_both_channels(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id = stored_item(client, manager)
    assert item_status(session, item_id) == ItemStatus.APPROVED
    assert {row["status"] for row in item_listings(manager, item_id).values()} == {"pending"}

    run_scheduler(session, market)

    assert item_status(session, item_id) == ItemStatus.LISTED
    listings = item_listings(manager, item_id)
    page = review(manager, item_id)
    for channel, listing in listings.items():
        remote = market.listing(channel, listing["channel_listing_id"])
        # The channel keeps the app's listing id, which makes a repeated publish return one listing.
        assert remote["external_ref"] == listing["id"]
        assert remote["status"] == "active"
        # The text staff wrote and the manager approved, at the price on the review page.
        drafted = next(row for row in page["listings"] if row["channel"] == channel.value)
        assert remote["title"] == drafted["title"] == "Carhartt canvas jacket - Pre-owned"
        assert remote["category"] == drafted["category"]
        assert remote["price_cents"] == drafted["price_cents"] == listing["price_cents"]
        assert remote["brand"] == "Carhartt"
        assert drafted["channel_status"] == "active"
    assert events(session, item_id) == [SyncEvent.PUBLISHED, SyncEvent.PUBLISHED]
    assert client.get(f"/items/{item_id}/listings").json() == list(listings.values())


def test_the_managers_price_goes_up_on_its_channel_only(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id = sent_item(client)
    response = manager.put(
        f"/items/{item_id}/listings/channel_b/price", json={"price_override_cents": 4500}
    )
    assert response.status_code == 200, response.text
    store(manager, item_id)
    assert approve(manager, item_id).status_code == 200
    store(manager, item_id, **SHELF)

    run_scheduler(session, market)

    listings = item_listings(manager, item_id)
    typical = review(manager, item_id)["listings"][0]["base_price_cents"]
    assert market.listing(B, listings[B]["channel_listing_id"])["price_cents"] == 4500
    assert market.listing(A, listings[A]["channel_listing_id"])["price_cents"] == typical


def test_an_item_held_for_its_season_waits_off_the_channels(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id = sent_item(client)
    row = item_row(session, item_id)
    row.release_month = utc_now().date().replace(year=utc_now().year + 1, day=1)
    session.add(row)
    session.commit()
    store(manager, item_id)
    assert approve(manager, item_id).json()["status"] == "held_for_season"

    assert store(manager, item_id, **SHELF).status_code == 200
    run_scheduler(session, market)

    assert item_listings(manager, item_id) == {}
    assert publish(manager, item_id).status_code == 409
    for channel in (A, B):
        assert market.adapters[channel].active_listings() == []


def test_publishing_again_makes_no_second_listing(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)

    again = publish(manager, item_id)
    store_again = store(manager, item_id, **SHELF)

    assert again.status_code == 200, again.text
    assert [row["id"] for row in again.json()] == [listing["id"] for listing in listings.values()]
    # Once listed, the shelf is set, so storing again is refused rather than publishing again.
    assert store_again.status_code == 409
    for channel in (A, B):
        assert len(market.adapters[channel].active_listings()) == 1


def test_only_a_manager_can_publish(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
) -> None:
    item_id = stored_item(client, manager)

    response = client.post(f"/items/{item_id}/listings")

    assert response.status_code == 403


def test_only_an_approved_item_on_a_shelf_can_be_published(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
) -> None:
    item_id, appraisal_id = appraised_item(client)
    assert decide(client, item_id, appraisal_id).status_code == 201
    unapproved = publish(manager, item_id)
    unshelved = publish(manager, approved_item(client, manager))

    message = "Only an approved item with a shelf or bin can be published."
    for response in (unapproved, unshelved):
        assert response.status_code == 409
        assert response.json()["detail"] == message


def test_a_game_goes_on_channel_a_only(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    model_replies(category="electronics_games", brand="Nintendo", product="Switch Lite console")
    use_drafter(
        draft_reply(
            "Video Game Consoles",
            title="Nintendo Switch Lite console - Pre-owned",
            description="Nintendo Switch Lite console, pre-owned.",
        )
    )

    item_id, listings = listed_item(client, manager, session, market)

    assert list(listings) == [A]
    assert item_status(session, item_id) == ItemStatus.LISTED
    remote = market.listing(A, listings[A]["channel_listing_id"])
    assert remote["category"] == "Video Game Consoles"
    assert market.adapters[B].active_listings() == []


def test_channel_b_refuses_a_listing_with_no_brand(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id = sent_item(client)
    # Staff took the brand off the card after the search, which Channel A allows and B doesn't.
    card = session.get(ItemCard, UUID(item_id))
    assert card is not None
    card.brand = None
    session.add(card)
    session.commit()
    assert store(manager, item_id).status_code == 200
    assert approve(manager, item_id).status_code == 200
    assert store(manager, item_id, **SHELF).status_code == 200

    run_scheduler(session, market)

    listings = item_listings(manager, item_id)
    assert listings[A]["status"] == "active"
    assert listings[B]["status"] == "rejected"
    assert listings[B]["status_detail"] == "Channel B refused it: Channel B needs a brand."
    page = review(manager, item_id)
    assert [row["channel_status"] for row in page["listings"]] == ["active", "rejected"]
    assert page["listings"][1]["channel_detail"] == listings[B]["status_detail"]
    assert item_status(session, item_id) == ItemStatus.LISTED
    assert SyncEvent.PUBLISH_REJECTED in events(session, item_id)
    # A refusal is final, so nothing is left to retry.
    assert pending_jobs(session) == []


def test_a_sale_on_one_channel_takes_the_item_down_from_the_other(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)

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
    # The sale goes through the manager's mark_sold, so the item is waiting on the pick list.
    picks = manager.get("/pick-list").json()
    assert [(row["item_id"], row["location_code"]) for row in picks] == [(item_id, "A3")]


def test_a_sale_that_beats_the_publish_answer_still_reaches_the_pick_list(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
    # The webhook for a sale can land before the publish job records the channel's answer.
    row = item_row(session, item_id)
    row.status = ItemStatus.APPROVED
    session.add(row)
    session.commit()

    market.buy(B, listings[B]["channel_listing_id"])

    assert item_status(session, item_id) == ItemStatus.SOLD
    assert listing_status(session, listings[A]) == ListingStatus.ENDED
    assert [row["item_id"] for row in manager.get("/pick-list").json()] == [item_id]


def test_polling_finds_a_sale_whose_webhook_never_arrived(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)

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
    manager: TestClient,  # noqa: F811
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
        item_id, listings = listed_item(client, manager, session, market)

        market.buy(A, listings[A]["channel_listing_id"])
        assert item_status(session, item_id) == ItemStatus.LISTED

        assert poll_channel(session, market.adapters[A]).orders == 1
        assert item_status(session, item_id) == ItemStatus.SOLD
    finally:
        market.close()


def test_a_failed_delist_is_retried_from_the_jobs_table(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
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
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
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
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
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
        "Carhartt canvas jacket - Pre-owned sold on Channel B and again on Channel A, so one of "
        "the orders needs cancelling."
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
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
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


def webhook(client: TestClient, channel: Channel, body: bytes, key: str | None = None) -> Any:  # noqa: F811
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
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
    body = order_body(listings[A])

    assert webhook(client, A, body).status_code == 204
    assert webhook(client, A, body).status_code == 204

    assert len(session.exec(select(SaleEvent)).all()) == 1
    assert events(session, item_id).count(SyncEvent.SALE_RECORDED) == 1
    assert flags(session) == []


def test_a_webhook_with_a_wrong_signature_is_refused(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)

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
        category="Unisex Clothing",
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
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    market.set_offline(B)
    item_id = stored_item(client, manager)

    run_scheduler(session, market)

    listings = item_listings(manager, item_id)
    assert listings[A]["status"] == "active"
    assert listings[B]["status"] == "pending"
    assert item_status(session, item_id) == ItemStatus.LISTED
    market.set_offline(B, False)
    run_jobs(session, dict(market.adapters), utc_now() + retry_delay(1))
    assert listing_status(session, listings[B]) == ListingStatus.ACTIVE
    assert len(market.adapters[B].active_listings()) == 1


def test_an_item_that_sells_before_a_publish_lands_is_not_listed_there(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    market.set_offline(B)
    item_id = stored_item(client, manager)
    run_scheduler(session, market)
    listings = item_listings(manager, item_id)
    market.buy(A, listings[A]["channel_listing_id"])
    market.set_offline(B, False)

    run_jobs(session, dict(market.adapters), utc_now() + timedelta(minutes=10))

    assert listing_status(session, listings[B]) == ListingStatus.ENDED
    assert SyncEvent.PUBLISH_SKIPPED in events(session, item_id)
    assert market.adapters[B].active_listings() == []
    assert pending_jobs(session) == []


def test_a_publish_that_gives_up_marks_the_listing_failed_and_the_manager_can_resend_it(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,
    session: Session,
) -> None:
    market.set_offline(B)
    item_id = stored_item(client, manager)
    now = utc_now()
    run_jobs(session, dict(market.adapters), now)
    for attempt in range(1, MAX_ATTEMPTS):
        now += retry_delay(attempt)
        run_jobs(session, dict(market.adapters), now)

    listings = item_listings(manager, item_id)
    assert listing_status(session, listings[B]) == ListingStatus.FAILED
    assert SyncEvent.PUBLISH_GAVE_UP in events(session, item_id)
    assert review(manager, item_id)["listings"][1]["channel_status"] == "failed"

    # Publishing again tries the failed channel once more, and leaves the live one alone.
    market.set_offline(B, False)
    response = publish(manager, item_id)
    assert response.status_code == 200, response.text
    again = {row["channel"]: row for row in response.json()}
    assert again["channel_b"]["status"] == "active"
    assert again["channel_b"]["id"] == listings[B]["id"]
    assert again["channel_a"] == listings[A]
    assert len(market.adapters[A].active_listings()) == 1


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
