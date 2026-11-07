"""The manager approval step, the storage step after it, and the pick list of sold items."""

import json
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.appraisal import get_photo_storage
from app.approval import PickListEntry, mark_sold, pick_order
from app.auth import get_token_verifier
from app.channel_timing import get_today
from app.channels import MockChannelAdapter, get_channels
from app.db import get_session
from app.main import app
from app.models import (
    Channel,
    Decision,
    DecisionChoice,
    DraftState,
    Item,
    ItemStatus,
    ListingDraft,
    Role,
)
from app.pricing import PriceRange, worth_listing
from app.storage import LocalStorage
from app.store_settings import StoreSettings, pricing_rules
from tests.test_appraisal import (
    MANAGER_TOKEN,
    REASON,
    STAFF_TOKEN,
    TODAY,
    StubVerifier,
    add_profile,
    appraised_item,
    as_token,
    decide,
    draft_reply,
    listed_item,
    listings,
    model_replies,
    serpapi_fixture,
    use_drafter,
    use_reasoner,
    use_search,
    write_drafts,
)

PACKAGE = {"package_weight_oz": 22.4, "box_code": "12x12x6"}


@pytest.fixture
def client(session: Session, tmp_path: Path) -> Iterator[TestClient]:
    """Staff, with every model and search stubbed the way the appraisal tests stub them."""
    tokens = {
        STAFF_TOKEN: add_profile(session, "staff1"),
        MANAGER_TOKEN: add_profile(session, "manager1", Role.MANAGER),
    }
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_photo_storage] = lambda: LocalStorage(tmp_path)
    app.dependency_overrides[get_token_verifier] = lambda: StubVerifier(tokens)
    # Both channels set up, at an address nothing answers, because no job runs in these tests.
    app.dependency_overrides[get_channels] = lambda: {
        channel: MockChannelAdapter.connect(channel, "http://channel.invalid", "key")
        for channel in Channel
    }
    model_replies()
    # Enough replies for every item a test drafts, Channel A then Channel B each time.
    use_drafter(*[draft_reply("Unisex Clothing"), draft_reply("Unisex")] * 6)
    use_reasoner(json.dumps({"reason": REASON}))
    app.dependency_overrides[get_today] = lambda: TODAY
    use_search(serpapi_fixture("carhartt-detroit-jacket"))
    yield TestClient(app, headers=as_token(STAFF_TOKEN))
    app.dependency_overrides.clear()


@pytest.fixture
def manager(client: TestClient) -> TestClient:
    return TestClient(app, headers=as_token(MANAGER_TOKEN))


def sent_item(client: TestClient) -> str:
    """An item staff said yes to and sent on with a draft for each channel."""
    item_id = listed_item(client)
    write_drafts(client, item_id)
    response = client.post(f"/items/{item_id}/drafts/submit")
    assert response.status_code == 200, response.text
    return item_id


def review(manager: TestClient, item_id: str) -> dict[str, Any]:
    response = manager.get(f"/items/{item_id}/review")
    assert response.status_code == 200, response.text
    return response.json()


def store(manager: TestClient, item_id: str, **body: Any) -> Any:
    return manager.put(f"/items/{item_id}/storage", json=PACKAGE | body)


def approve(manager: TestClient, item_id: str) -> Any:
    return manager.post(f"/items/{item_id}/approve")


def approved_item(client: TestClient, manager: TestClient) -> str:
    item_id = sent_item(client)
    assert store(manager, item_id).status_code == 200
    assert approve(manager, item_id).status_code == 200
    return item_id


def stored_item(client: TestClient, manager: TestClient, box: str, shelf: str) -> str:
    item_id = approved_item(client, manager)
    response = store(manager, item_id, box_code=box, location_code=shelf)
    assert response.status_code == 200, response.text
    return item_id


def item_row(session: Session, item_id: str) -> Item:
    row = session.get(Item, UUID(item_id), populate_existing=True)
    assert row is not None
    return row


def set_status(session: Session, item_id: str, status: ItemStatus) -> None:
    row = item_row(session, item_id)
    row.status = status
    session.add(row)
    session.commit()


def sold(session: Session, item_id: str) -> None:
    """No channel runs in these tests, so the test lists the item by hand before the sale.

    tests/test_sync.py runs the channels, where a real sale calls `mark_sold` the same way.
    """
    set_status(session, item_id, ItemStatus.LISTED)
    mark_sold(session, UUID(item_id))
    session.commit()


def test_the_whole_path_from_sent_on_to_picked(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    item_id = sent_item(client)
    queue = manager.get("/approvals").json()
    assert [entry["item_id"] for entry in queue["awaiting_approval"]] == [item_id]
    assert queue["awaiting_approval"][0]["channels"] == ["channel_a", "channel_b"]
    assert queue["awaiting_storage"] == []

    page = review(manager, item_id)
    assert page["status"] == "appraised"
    assert page["submitted_by_name"] == "Staff1"
    assert [listing["state"] for listing in page["listings"]] == ["awaiting_approval"] * 2
    assert page["blockers"] == [
        "Enter the package weight and box size, which Channel A needs before approval."
    ]

    page = store(manager, item_id).json()
    assert page["blockers"] == []
    assert re.fullmatch(r"ST\d{8}", page["sku"])
    assert page["full_sku"] == f"{page['sku']} 12x12x6"

    page = approve(manager, item_id).json()
    assert page["status"] == "approved"
    assert [listing["state"] for listing in page["listings"]] == ["approved"] * 2
    queue = manager.get("/approvals").json()
    assert queue["awaiting_approval"] == []
    assert [entry["item_id"] for entry in queue["awaiting_storage"]] == [item_id]

    page = store(manager, item_id, location_code=" b12 - 2 ").json()
    assert page["location_code"] == "B12-2"
    # Stored, so each listing waits for the scheduler to put it up on its channel.
    assert [listing["channel_status"] for listing in page["listings"]] == ["pending"] * 2
    assert manager.get("/approvals").json()["awaiting_storage"] == []
    drafts = session.exec(select(ListingDraft).where(ListingDraft.item_id == UUID(item_id))).all()
    assert all(draft.reviewed_at is not None for draft in drafts)

    sold(session, item_id)
    entries = client.get("/pick-list").json()
    assert [entry["full_sku"] for entry in entries] == [page["full_sku"]]
    assert entries[0]["title"] == "Carhartt canvas jacket - Pre-owned"
    assert entries[0]["location_code"] == "B12-2"

    assert client.post(f"/items/{item_id}/picked").status_code == 204
    assert item_row(session, item_id).status is ItemStatus.PICKED
    assert client.get("/pick-list").json() == []
    assert client.post(f"/items/{item_id}/picked").status_code == 409


MANAGER_ROUTES = [
    ("get", "/approvals", None),
    ("get", "/items/{id}/review", None),
    ("put", "/items/{id}/listings/channel_a/price", {"price_override_cents": 5000}),
    ("put", "/items/{id}/storage", PACKAGE),
    ("post", "/items/{id}/approve", None),
    ("post", "/items/{id}/reject", {"reason": "Not our kind of item"}),
]


@pytest.mark.parametrize(("method", "path", "body"), MANAGER_ROUTES)
def test_only_a_manager_can_review_price_store_approve_or_reject(
    client: TestClient,
    session: Session,
    method: str,
    path: str,
    body: Any,
) -> None:
    item_id = sent_item(client)
    url = path.format(id=item_id)
    response = client.request(method, url, json=body)
    assert response.status_code == 403
    assert response.json()["detail"] == "Only a manager can do this."
    assert TestClient(app).request(method, url, json=body).status_code == 401
    row = item_row(session, item_id)
    assert row.status is ItemStatus.APPRAISED
    assert row.box_code is None
    drafts = session.exec(select(ListingDraft).where(ListingDraft.item_id == UUID(item_id))).all()
    assert all(draft.state is DraftState.AWAITING_APPROVAL for draft in drafts)
    assert all(draft.price_override_cents is None for draft in drafts)


def test_channel_a_needs_the_package_before_approval(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    item_id = sent_item(client)
    response = approve(manager, item_id)
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Enter the package weight and box size, which Channel A needs before approval."
    )
    assert item_row(session, item_id).status is ItemStatus.APPRAISED


def test_storage_before_approval_takes_the_package_but_no_shelf(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    item_id = sent_item(client)
    response = store(manager, item_id, location_code="A3")
    assert response.status_code == 409
    assert response.json()["detail"] == "Add the shelf or bin code once the item is approved."
    assert item_row(session, item_id).box_code is None


def test_the_package_waits_for_staff_to_send_the_listing_on(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = listed_item(client)
    write_drafts(client, item_id)
    response = store(manager, item_id)
    assert response.status_code == 409
    assert response.json()["detail"] == "Staff haven't sent this listing for approval yet."
    assert review(manager, item_id)["blockers"] == [
        "Staff haven't sent this listing for approval yet."
    ]
    assert approve(manager, item_id).status_code == 409
    assert manager.get("/approvals").json()["awaiting_approval"] == []


def test_an_approved_item_needs_a_shelf_to_be_stored(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = approved_item(client, manager)
    response = store(manager, item_id)
    assert response.status_code == 422
    assert response.json()["detail"] == "Enter the shelf or bin code."


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"package_weight_oz": 0}, "Enter a package weight above 0 oz."),
        ({"package_weight_oz": 12.25}, "Weigh the package to the nearest tenth of an ounce."),
        ({"package_weight_oz": 1121}, "1121 oz is over the 70 lb shipping limit."),
        ({"box_code": "11x11x11"}, "Choose one of the box sizes in Settings."),
        ({"location_code": "A3/7"}, "at most 20 letters, numbers, spaces and dashes"),
        ({"location_code": "A" * 21}, "at most 20 letters, numbers, spaces and dashes"),
    ],
)
def test_a_package_or_shelf_the_store_cant_use_is_refused(
    client: TestClient,
    manager: TestClient,
    session: Session,
    body: dict[str, Any],
    message: str,
) -> None:
    item_id = approved_item(client, manager)
    response = store(manager, item_id, **({"location_code": "A3"} | body))
    assert response.status_code == 422
    assert message in response.json()["detail"]
    row = item_row(session, item_id)
    assert (row.package_weight_oz, row.box_code, row.location_code) == (22.4, "12x12x6", None)


def test_the_box_must_still_be_in_settings(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = sent_item(client)
    page = manager.get("/settings").json()["box_sizes"]
    small = {"kind": "box", "length_in": 8, "width_in": 6, "height_in": 4}
    response = manager.put(
        "/settings/box-sizes",
        json={"value": {"boxes": [small]}, "expected_updated_at": page["updated_at"]},
    )
    assert response.status_code == 200, response.text
    assert store(manager, item_id).status_code == 422
    assert store(manager, item_id, box_code="8x6x4").status_code == 200


def test_the_billed_weight_follows_the_shipping_rules(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = sent_item(client)
    assert (
        store(manager, item_id, package_weight_oz=3.5, box_code="10x13").json()["billed_weight_oz"]
        == 4
    )
    assert store(manager, item_id, package_weight_oz=17).json()["billed_weight_oz"] == 32
    # 16x12x8 is 1536 cubic inches, under the size-weight line, so the weight decides.
    assert (
        store(manager, item_id, package_weight_oz=8, box_code="16x12x8").json()["billed_weight_oz"]
        == 8
    )


def test_a_box_over_the_size_line_is_billed_by_its_size() -> None:
    current = StoreSettings()
    big = current.box_sizes.boxes[-1].model_copy(update={"height_in": 10})
    # 16x12x10 is 1920 cubic inches, which bills as ceil(1920 / 139) = 14 lb.
    assert current.shipping_weight.billed_weight_oz(8, big) == 14 * 16


def test_a_price_override_changes_the_price_and_the_net_for_its_channel_only(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = sent_item(client)
    before = review(manager, item_id)
    typical = before["appraisal"]["price_typical_cents"]
    a, b = before["listings"]
    assert a["price_cents"] == b["price_cents"] == a["base_price_cents"] == typical

    response = manager.put(
        f"/items/{item_id}/listings/channel_b/price", json={"price_override_cents": 1200}
    )
    assert response.status_code == 200, response.text
    a, b = response.json()["listings"]
    assert (a["price_override_cents"], a["price_cents"]) == (None, typical)
    assert (b["price_override_cents"], b["price_cents"]) == (1200, 1200)
    # Under $15 Channel B charges its $2.95 flat fee, and the $1.50 supplies come on top.
    assert b["net_after_fees_cents"] == 1200 - 295 - 150

    response = manager.put(
        f"/items/{item_id}/listings/channel_b/price", json={"price_override_cents": None}
    )
    assert response.json()["listings"][1]["price_cents"] == typical


def test_the_channel_a_net_is_the_worth_listing_net(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    item_id = sent_item(client)
    page = review(manager, item_id)
    typical = page["appraisal"]["price_typical_cents"]
    expected = worth_listing(
        PriceRange(
            low_cents=None,
            typical_cents=typical,
            high_cents=None,
            comps_count=0,
            trimmed=[],
            confidence=page["appraisal"]["confidence"],
        ),
        pricing_rules(session),
    ).net_after_fees_cents
    assert page["listings"][0]["net_after_fees_cents"] == expected


@pytest.mark.parametrize(
    ("price", "net"),
    [
        (1499, 1499 - 295 - 150),
        (1500, 1500 - 300 - 150),
        (4999, 4999 - 1000 - 150),
    ],
)
def test_channel_b_charges_a_flat_fee_below_15_dollars_and_a_share_above(
    price: int, net: int
) -> None:
    assert StoreSettings().channel_b_fees.net_cents(price) == net


@pytest.mark.parametrize("cents", [0, -100, 10_000_001])
def test_a_price_override_must_be_a_real_price(
    client: TestClient,
    manager: TestClient,
    cents: int,
) -> None:
    item_id = sent_item(client)
    response = manager.put(
        f"/items/{item_id}/listings/channel_a/price", json={"price_override_cents": cents}
    )
    assert response.status_code == 422


def test_an_approved_listing_cant_be_repriced(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = approved_item(client, manager)
    response = manager.put(
        f"/items/{item_id}/listings/channel_a/price", json={"price_override_cents": 5000}
    )
    assert response.status_code == 409


def test_a_game_has_no_channel_b_listing_to_price(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = sent_item(client)
    response = manager.put(
        f"/items/{item_id}/listings/channel_c/price", json={"price_override_cents": 5000}
    )
    assert response.status_code == 422


def test_an_appraisal_with_no_typical_price_needs_a_price_for_each_channel(
    client: TestClient,
    manager: TestClient,
) -> None:
    use_search(listings())
    item_id, appraisal_id = appraised_item(client)
    assert decide(client, item_id, appraisal_id).status_code == 201
    write_drafts(client, item_id)
    assert client.post(f"/items/{item_id}/drafts/submit").status_code == 200
    store(manager, item_id)

    page = review(manager, item_id)
    assert [listing["net_after_fees_cents"] for listing in page["listings"]] == [None, None]
    assert page["blockers"] == [
        "Set a price for Channel A, because the appraisal found no typical sale price.",
        "Set a price for Channel B, because the appraisal found no typical sale price.",
    ]
    for channel in ("channel_a", "channel_b"):
        manager.put(
            f"/items/{item_id}/listings/{channel}/price", json={"price_override_cents": 4500}
        )
    assert approve(manager, item_id).status_code == 200


def test_storing_publishes_nothing_while_no_channel_is_set_up(
    client: TestClient,
    manager: TestClient,
) -> None:
    app.dependency_overrides[get_channels] = lambda: {}
    item_id = approved_item(client, manager)

    page = store(manager, item_id, location_code="A3").json()

    assert page["status"] == "approved"
    assert [listing["channel_status"] for listing in page["listings"]] == [None, None]
    response = manager.post(f"/items/{item_id}/listings")
    assert response.status_code == 409
    assert response.json()["detail"] == "No sales channel is set up on this server."


def test_an_item_with_a_later_release_month_is_held_and_keeps_it(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    item_id = sent_item(client)
    later = date(TODAY.year + 1, TODAY.month, 1)
    row = item_row(session, item_id)
    row.release_month = later
    session.add(row)
    session.commit()

    store(manager, item_id)
    page = approve(manager, item_id).json()
    assert page["status"] == "held_for_season"
    assert page["release_month"] == later.isoformat()
    queue = manager.get("/approvals").json()
    assert [entry["status"] for entry in queue["awaiting_storage"]] == ["held_for_season"]

    page = store(manager, item_id, location_code="C1").json()
    assert page["status"] == "held_for_season"
    # It goes up on the channels when its season comes, not when it is stored.
    assert [listing["channel_status"] for listing in page["listings"]] == [None, None]
    assert item_row(session, item_id).release_month == later


def test_an_item_whose_release_month_has_come_is_approved(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    item_id = sent_item(client)
    row = item_row(session, item_id)
    row.release_month = TODAY.replace(day=1)
    session.add(row)
    session.commit()
    store(manager, item_id)
    assert approve(manager, item_id).json()["status"] == "approved"


def test_a_rejected_item_records_a_no_and_skips_storage(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    item_id = sent_item(client)
    response = manager.post(
        f"/items/{item_id}/reject", json={"reason": " Too worn to sell ", "note": "Seam split"}
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["status"] == "declined"
    assert [listing["state"] for listing in page["listings"]] == ["rejected"] * 2
    assert page["blockers"] == []

    decisions = session.exec(
        select(Decision).where(Decision.item_id == UUID(item_id)).order_by(col(Decision.decided_at))
    ).all()
    assert [d.decision for d in decisions] == [DecisionChoice.YES, DecisionChoice.NO]
    assert decisions[-1].override_reason == "Too worn to sell"
    assert decisions[-1].note == "Seam split"

    queue = manager.get("/approvals").json()
    assert queue == {
        "awaiting_approval": [],
        "awaiting_storage": [],
        "held_for_season": [],
        "not_listed_online": [],
    }
    assert store(manager, item_id, location_code="A3").status_code == 409
    assert approve(manager, item_id).status_code == 409


def test_a_rejection_needs_a_reason(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = sent_item(client)
    assert manager.post(f"/items/{item_id}/reject", json={"reason": "  "}).status_code == 422


def test_saying_yes_again_after_a_rejection_lets_staff_edit_and_send_again(
    client: TestClient,
    manager: TestClient,
) -> None:
    item_id = sent_item(client)
    page = review(manager, item_id)
    manager.post(f"/items/{item_id}/reject", json={"reason": "Fix the title"})

    assert decide(client, item_id, page["appraisal"]["id"]).status_code == 201
    drafts = client.get(f"/items/{item_id}/drafts").json()
    assert [draft["state"] for draft in drafts] == ["draft", "draft"]
    response = client.patch(f"/items/{item_id}/drafts/channel_a", json={"title": "Carhartt coat"})
    assert response.status_code == 200, response.text
    assert client.post(f"/items/{item_id}/drafts/submit").status_code == 200
    queue = manager.get("/approvals").json()
    assert [entry["item_id"] for entry in queue["awaiting_approval"]] == [item_id]


def test_the_queues_are_oldest_first(
    client: TestClient,
    manager: TestClient,
) -> None:
    first, second = sent_item(client), sent_item(client)
    queue = manager.get("/approvals").json()
    assert [entry["item_id"] for entry in queue["awaiting_approval"]] == [first, second]


def test_mark_sold_needs_a_listed_item(client: TestClient, session: Session) -> None:
    item_id = listed_item(client)
    with pytest.raises(ValueError, match="appraised can't be sold"):
        mark_sold(session, UUID(item_id))
    with pytest.raises(LookupError):
        mark_sold(session, UUID(int=0))


def test_the_pick_list_is_by_box_section_then_shelf(
    client: TestClient,
    manager: TestClient,
    session: Session,
) -> None:
    # The Settings list has the 10x13 mailer before the 12x12x6 box.
    placed = [
        ("12x12x6", "A10"),
        ("12x12x6", "A2"),
        ("10x13", "B1"),
        ("12x12x6", "A2-1"),
    ]
    ids = [stored_item(client, manager, box, shelf) for box, shelf in placed]
    unsold = stored_item(client, manager, "10x13", "A1")
    for item_id in ids:
        sold(session, item_id)

    entries = client.get("/pick-list", headers=as_token(STAFF_TOKEN)).json()
    assert [(entry["box_code"], entry["location_code"]) for entry in entries] == [
        ("10x13", "B1"),
        ("12x12x6", "A2"),
        ("12x12x6", "A2-1"),
        ("12x12x6", "A10"),
    ]
    assert unsold not in {entry["item_id"] for entry in entries}
    assert manager.get("/pick-list").json() == entries


def entry(sku: str, box: str | None, shelf: str | None) -> PickListEntry:
    return PickListEntry(
        item_id=UUID(int=0),
        sku=sku,
        full_sku=None,
        title=sku,
        box_code=box,
        location_code=shelf,
        package_weight_oz=None,
    )


def test_a_box_gone_from_settings_and_no_box_come_last() -> None:
    entries = [
        entry("RT1", None, "A1"),
        entry("RT2", "20x20x20", "A1"),
        entry("RT3", "8x6x4", None),
        entry("RT4", "8x6x4", "Z9"),
        entry("RT5", "10x13", "A1"),
    ]
    assert [e.sku for e in pick_order(entries, StoreSettings())] == [
        "RT5",
        "RT4",
        "RT3",
        "RT2",
        "RT1",
    ]


def test_the_pick_list_needs_a_sign_in() -> None:
    assert TestClient(app).get("/pick-list").status_code == 401
