"""The Needs Attention screen, end to end against both mock channels and real Postgres.

Each conflict is planted the way it happens for real, with sales on the storefronts, lost
webhooks and a channel switched offline, and the screen is read through the API as staff see
it. The model that explains a flag is stubbed, as in the appraisal tests.
"""

import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.channels import ChannelRejectedError, ListingContent
from app.flag_explanations import PROMPT, explain_open_flags
from app.jobs import MAX_ATTEMPTS, utc_now
from app.main import app
from app.models import (
    Channel,
    ConflictKind,
    DraftSource,
    FallbackReason,
    FlagExplanation,
    ItemStatus,
    Job,
    JobKind,
    JobStatus,
    ListingStatus,
    SaleEvent,
    SyncEvent,
)
from app.sync import poll_channel, poll_channels, retry_delay, run_jobs
from tests.channel_harness import Market
from tests.test_appraisal import StubChat
from tests.test_approval import client, manager  # noqa: F401, the fixtures these tests build on
from tests.test_sync import (
    events,
    flags,
    item_status,
    listed_item,
    listing_status,
    market,  # noqa: F401
    pending_jobs,
)

A, B = Channel.CHANNEL_A, Channel.CHANNEL_B
TITLE = "Carhartt canvas jacket - Pre-owned"
HAND_LISTING = ListingContent(
    title="Listed by hand",
    description="Someone listed this on the channel directly.",
    category="Unisex",
    condition="pre_owned",
    price_cents=1200,
    brand="Levi's",
)


def attention(client: TestClient) -> dict[str, Any]:  # noqa: F811
    response = client.get("/attention")
    assert response.status_code == 200, response.text
    return response.json()


def open_flags(client: TestClient, conflict: ConflictKind | None = None) -> list[dict[str, Any]]:  # noqa: F811
    rows = attention(client)["open"]
    return [row for row in rows if conflict is None or row["conflict"] == conflict]


def double_sale(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
    market: Market,  # noqa: F811
) -> tuple[str, dict[Channel, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """A sells first with its webhook lost, then B sells and its webhook arrives."""
    item_id, listings = listed_item(client, manager, session, market)
    first = market.buy(A, listings[A]["channel_listing_id"], send_webhook=False)
    second = market.buy(B, listings[B]["channel_listing_id"])
    return item_id, listings, first, second


def order_status(market: Market, channel: Channel, order_id: str) -> str:  # noqa: F811
    [order] = [
        row
        for row in market.adapters[channel].client.get("/orders").json()
        if row["id"] == order_id
    ]
    return order["status"]


def explain(market: Market, *providers: StubChat) -> int:  # noqa: F811
    """What the scheduler's explainer thread does every few seconds."""
    return explain_open_flags(market.factory, list(providers))


def explanation(session: Session, flag_id: str) -> FlagExplanation:
    session.expire_all()
    return session.get_one(FlagExplanation, UUID(flag_id))


# Planting each conflict


def test_a_double_sale_shows_which_order_keeps_the_item(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    item_id, _, first, second = double_sale(client, manager, session, market)

    [row] = open_flags(client)
    assert row["conflict"] == "double_sale"
    assert row["item_id"] == item_id
    assert row["title"] == TITLE
    assert row["sku"].endswith(" 12x12x6")
    assert row["double_sale"]["keep"]["channel"] == A
    assert row["double_sale"]["keep"]["channel_order_id"] == first["id"]
    assert row["double_sale"]["cancel"]["channel"] == B
    assert row["double_sale"]["cancel"]["channel_order_id"] == second["id"]
    assert row["double_sale"]["cancelling"] is None
    # The explainer hasn't run, so the fixed sentences show straight away.
    assert row["explained_by"] is None
    assert row["explanation"] == (
        f"{TITLE} sold on Channel A and then again on Channel B, but the store has only one to "
        "send."
    )
    assert row["suggested_fix"] == (
        "Cancel the Channel B order, which refunds that buyer, so the Channel A buyer who paid "
        "first keeps the item."
    )
    assert row["resolved_at"] is None


def test_a_double_sale_while_a_channel_was_offline_is_flagged(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
    market.set_offline(B)
    first = market.buy(A, listings[A]["channel_listing_id"])
    market.set_offline(B, False)
    # B sold before its end job came round again.
    second = market.buy(B, listings[B]["channel_listing_id"])

    [row] = open_flags(client)
    assert row["conflict"] == "double_sale"
    assert row["double_sale"]["keep"]["channel_order_id"] == first["id"]
    assert row["double_sale"]["cancel"]["channel_order_id"] == second["id"]
    assert item_status(session, item_id) == ItemStatus.SOLD


def test_a_stale_listing_is_flagged_once_its_channel_is_back(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    item_id, listings = listed_item(client, manager, session, market)
    market.set_offline(B)
    market.buy(A, listings[A]["channel_listing_id"])
    now = utc_now()
    for attempt in range(1, MAX_ATTEMPTS):
        now += retry_delay(attempt)
        run_jobs(session, dict(market.adapters), now)
    # Polling B while it is down raises nothing, and A is still polled.
    poll_channels(market.factory, dict(market.adapters))
    assert open_flags(client) == []

    market.set_offline(B, False)
    poll_channels(market.factory, dict(market.adapters))

    [row] = open_flags(client)
    assert row["conflict"] == "stale_listing"
    assert row["channel"] == B
    assert row["item_id"] == item_id
    assert row["channel_listing_id"] == listings[B]["channel_listing_id"]
    assert row["double_sale"] is None
    assert row["explanation"] == (
        f"{TITLE} is still up for sale on Channel B, but the item has already sold, so a buyer "
        "there could pay for something the store can't send."
    )
    assert row["suggested_fix"].startswith("Turnstone is already trying again to take it down.")


def test_unknown_listings_and_orders_are_flagged_while_the_other_channel_is_offline(
    client: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    stranger = market.adapters[B].publish(uuid4(), HAND_LISTING)
    sold = market.adapters[B].publish(uuid4(), HAND_LISTING)
    order = market.buy(B, sold.id, send_webhook=False)
    market.set_offline(A)

    poll_channels(market.factory, dict(market.adapters))

    rows = open_flags(client, ConflictKind.UNKNOWN_LISTING)
    by_listing = {row["channel_listing_id"]: row for row in rows}
    assert set(by_listing) == {stranger.id, sold.id}
    assert by_listing[stranger.id]["channel_order_id"] is None
    assert by_listing[stranger.id]["explanation"].startswith(
        "Channel B has a listing up for sale that isn't in Turnstone"
    )
    assert by_listing[sold.id]["channel_order_id"] == order["id"]
    assert by_listing[sold.id]["explanation"].startswith(
        "Channel B took an order for a listing that isn't in Turnstone"
    )
    assert all(row["item_id"] is None and row["title"] is None for row in rows)


def test_staff_and_managers_both_see_the_screen_and_nobody_else(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
) -> None:
    assert client.get("/attention").json() == {"open": [], "resolved": []}
    assert manager.get("/attention").status_code == 200
    assert TestClient(app).get("/attention").status_code == 401
    assert TestClient(app).post(f"/attention/{uuid4()}/fix").status_code == 401


# The one-click fix


def test_staff_fix_a_double_sale_in_one_click(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    item_id, listings, first, second = double_sale(client, manager, session, market)
    [row] = open_flags(client)

    response = client.post(f"/attention/{row['id']}/fix")

    assert response.status_code == 200, response.text
    fixed = response.json()
    assert fixed["resolved_at"] is not None
    assert fixed["resolved_by"] == "Staff1"
    assert (
        fixed["resolution"]
        == "Cancelled the Channel B order, so the Channel A buyer keeps the item."
    )
    assert order_status(market, B, second["id"]) == "cancelled"
    assert order_status(market, A, first["id"]) == "paid"
    assert market.listing(B, listings[B]["channel_listing_id"])["status"] == "ended"
    assert listing_status(session, listings[B]) == ListingStatus.ENDED
    assert listing_status(session, listings[A]) == ListingStatus.SOLD
    assert item_status(session, item_id) == ItemStatus.SOLD
    cancelled = session.exec(
        select(SaleEvent).where(SaleEvent.channel_order_id == second["id"])
    ).one()
    assert cancelled.cancelled_at is not None
    assert SyncEvent.ORDER_CANCELLED in events(session, item_id)
    assert attention(client)["open"] == []
    [resolved] = attention(client)["resolved"]
    assert resolved["id"] == row["id"]
    assert resolved["double_sale"] is None
    assert pending_jobs(session) == []
    # Polling afterwards finds nothing new on either channel.
    for channel in (A, B):
        assert poll_channel(session, market.adapters[channel]).flags == 0


def test_the_first_buyer_keeps_it_whichever_order_turnstone_heard_of_first(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    _, listings = listed_item(client, manager, session, market)
    # B sells first, but its webhook is lost, so Turnstone hears of A's later order first.
    first = market.buy(B, listings[B]["channel_listing_id"], send_webhook=False)
    second = market.buy(A, listings[A]["channel_listing_id"])
    poll_channel(session, market.adapters[B])
    [row] = open_flags(client)
    assert row["double_sale"]["keep"]["channel_order_id"] == first["id"]

    fixed = client.post(f"/attention/{row['id']}/fix").json()

    assert (
        fixed["resolution"]
        == "Cancelled the Channel A order, so the Channel B buyer keeps the item."
    )
    assert order_status(market, A, second["id"]) == "cancelled"
    assert order_status(market, B, first["id"]) == "paid"


def test_a_cancel_while_the_channel_is_offline_is_retried_until_it_lands(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    item_id, _, _, second = double_sale(client, manager, session, market)
    [row] = open_flags(client)
    market.set_offline(B)

    response = client.post(f"/attention/{row['id']}/fix")

    assert response.status_code == 200, response.text
    waiting = response.json()
    assert waiting["resolved_at"] is None
    cancelling = waiting["double_sale"]["cancelling"]
    assert cancelling["status"] == "pending"
    assert (cancelling["attempts"], cancelling["max_attempts"]) == (1, MAX_ATTEMPTS)
    assert "Channel B is offline" in cancelling["last_error"]
    assert SyncEvent.CANCEL_FAILED in events(session, item_id)
    # Pressing again while the retry is due queues no second cancel.
    assert client.post(f"/attention/{row['id']}/fix").status_code == 200
    assert len(session.exec(select(Job).where(Job.kind == JobKind.CANCEL_ORDER)).all()) == 1

    market.set_offline(B, False)
    run_jobs(session, dict(market.adapters), utc_now() + retry_delay(1))

    assert order_status(market, B, second["id"]) == "cancelled"
    [resolved] = attention(client)["resolved"]
    assert resolved["resolved_by"] == "Staff1"
    assert attention(client)["open"] == []


def test_a_cancel_that_gives_up_leaves_the_flag_to_try_again(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    item_id, _, _, second = double_sale(client, manager, session, market)
    [row] = open_flags(client)
    market.set_offline(B)
    client.post(f"/attention/{row['id']}/fix")
    now = utc_now()
    for attempt in range(1, MAX_ATTEMPTS):
        now += retry_delay(attempt)
        assert run_jobs(session, dict(market.adapters), now) == 1

    [row] = open_flags(client)
    assert row["double_sale"]["cancelling"]["status"] == "failed"
    assert SyncEvent.CANCEL_GAVE_UP in events(session, item_id)

    market.set_offline(B, False)
    fixed = client.post(f"/attention/{row['id']}/fix").json()

    assert fixed["resolved_at"] is not None
    assert order_status(market, B, second["id"]) == "cancelled"


def test_a_cancel_the_channel_refuses_stays_open_with_its_reason(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id, _, _, second = double_sale(client, manager, session, market)
    [row] = open_flags(client)

    def refuse(order_id: str) -> None:
        raise ChannelRejectedError("Channel B can't cancel an order that has shipped.")

    monkeypatch.setattr(market.adapters[B], "cancel_order", refuse)
    fixed = client.post(f"/attention/{row['id']}/fix").json()

    assert fixed["resolved_at"] is None
    cancelling = fixed["double_sale"]["cancelling"]
    assert cancelling["status"] == "failed"
    assert cancelling["attempts"] == 1
    assert cancelling["last_error"] == "Channel B can't cancel an order that has shipped."
    assert SyncEvent.CANCEL_REJECTED in events(session, item_id)
    assert order_status(market, B, second["id"]) == "paid"


def test_only_an_open_double_sale_can_be_fixed_in_one_click(
    client: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    market.adapters[B].publish(uuid4(), HAND_LISTING)
    poll_channel(session, market.adapters[B])
    [row] = open_flags(client)

    assert client.post(f"/attention/{row['id']}/fix").status_code == 409
    assert client.post(f"/attention/{uuid4()}/fix").status_code == 404
    assert client.post(f"/attention/{row['id']}/resolve", json={}).status_code == 200
    again = client.post(f"/attention/{row['id']}/resolve", json={})
    assert (again.status_code, again.json()["detail"]) == (409, "Someone has already handled this.")


def test_any_flag_can_be_marked_handled_with_a_note(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    market.adapters[B].publish(uuid4(), HAND_LISTING)
    poll_channel(session, market.adapters[B])
    [row] = open_flags(client)

    response = manager.post(
        f"/attention/{row['id']}/resolve", json={"note": "  Ended it on Channel B by hand.  "}
    )

    assert response.status_code == 200, response.text
    assert response.json()["resolution"] == "Ended it on Channel B by hand."
    assert response.json()["resolved_by"] == "Manager1"
    [entry] = flags(session)
    assert entry.resolved_by is not None
    assert attention(client)["open"] == []
    assert [row["id"] for row in attention(client)["resolved"]] == [str(entry.id)]


# Explaining a flag


def model_text(**changes: str) -> str:
    text = {
        "explanation": "The jacket sold on both channels, and there's only one of it.",
        "suggested_fix": "Cancel the Channel B order so the Channel A buyer gets the jacket.",
    }
    return json.dumps(text | changes)


def test_the_model_rewords_a_flag_from_the_facts_code_found(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    double_sale(client, manager, session, market)
    model = StubChat(model_text(), name="explainer")

    assert explain(market, model) == 1
    assert explain(market, model) == 0

    [row] = open_flags(client)
    assert row["explained_by"] == "model"
    assert row["explanation"] == "The jacket sold on both channels, and there's only one of it."
    assert row["suggested_fix"] == (
        "Cancel the Channel B order so the Channel A buyer gets the jacket."
    )
    written = explanation(session, row["id"])
    assert (written.source, written.fallback_reason, written.model_name) == (
        DraftSource.MODEL,
        None,
        "explainer",
    )
    [messages] = model.calls
    prompt = messages[0]["content"]
    assert prompt.startswith(PROMPT.split("\n", 1)[0])
    assert "- Kind of problem: Double sale" in prompt
    assert "- Order that keeps the item: Channel A" in prompt
    assert "- Order to cancel: Channel B" in prompt
    assert "- Fix: Cancel the Channel B order, which refunds that buyer" in prompt
    # Prices and times stay out, so the model has no number to get wrong.
    assert "$" not in prompt


def test_a_failed_model_call_still_shows_the_flag_with_the_fixed_text(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    double_sale(client, manager, session, market)

    assert explain(market, StubChat(500), StubChat(503, name="fallback")) == 1

    [row] = open_flags(client)
    assert row["explained_by"] == "template"
    assert row["explanation"].endswith("but the store has only one to send.")
    assert row["double_sale"]["cancel"]["channel"] == B
    written = explanation(session, row["id"])
    assert written.fallback_reason == FallbackReason.MODEL_FAILED


def test_a_model_reply_with_a_number_the_facts_lack_is_refused(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    double_sale(client, manager, session, market)
    model = StubChat(model_text(suggested_fix="Refund the Channel B buyer within 3 days."))

    explain(market, model)

    [row] = open_flags(client)
    assert row["explained_by"] == "template"
    assert row["suggested_fix"].startswith("Cancel the Channel B order, which refunds that buyer")
    written = explanation(session, row["id"])
    assert (written.fallback_reason, written.model_name) == (FallbackReason.FLAGGED, "primary")


def test_with_no_model_set_up_every_flag_gets_the_fixed_text(
    client: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    market.adapters[B].publish(uuid4(), HAND_LISTING)
    poll_channel(session, market.adapters[B])

    assert explain(market) == 1

    [row] = open_flags(client)
    assert row["explained_by"] == "template"
    assert explanation(session, row["id"]).fallback_reason == FallbackReason.NOT_CONFIGURED


def test_a_slow_model_never_holds_up_the_sync(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    """The explainer runs apart from the jobs, so a sale's delist is done before any model call."""
    item_id, listings = listed_item(client, manager, session, market)
    market.buy(A, listings[A]["channel_listing_id"])

    assert listing_status(session, listings[B]) == ListingStatus.ENDED
    assert session.exec(select(FlagExplanation)).all() == []
    assert SyncEvent.FLAGGED not in events(session, item_id)


def test_only_open_flags_wait_for_an_explanation(
    client: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    market.adapters[B].publish(uuid4(), HAND_LISTING)
    poll_channel(session, market.adapters[B])
    [row] = open_flags(client)
    client.post(f"/attention/{row['id']}/resolve", json={})

    model = StubChat(model_text())

    assert explain(market, model) == 0
    assert model.calls == []


def test_the_cancel_job_is_listed_with_the_other_channel_jobs(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    _, listings, _, second = double_sale(client, manager, session, market)
    [row] = open_flags(client)
    market.set_offline(B)
    client.post(f"/attention/{row['id']}/fix")
    session.expire_all()

    [job] = session.exec(select(Job).where(Job.kind == JobKind.CANCEL_ORDER)).all()

    assert job.status == JobStatus.PENDING
    assert job.payload == {
        "listing_id": listings[B]["id"],
        "channel_order_id": second["id"],
        "flag_id": row["id"],
        "requested_by": job.payload["requested_by"],
    }
    assert job.run_after > utc_now() + timedelta(seconds=1)
