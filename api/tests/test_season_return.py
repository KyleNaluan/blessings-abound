"""A held item coming back for review in its season, early, or not going online at all."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.channel_timing import get_today
from app.main import app
from app.models import Appraisal, CompSearch, ItemStatus, Listing
from tests.test_appraisal import TODAY, StubSearch, listed_item, serpapi_fixture, use_search
from tests.test_approval import (  # noqa: F401, the fixtures these tests build on
    PACKAGE,
    approve,
    client,
    item_row,
    manager,
    review,
    sent_item,
    store,
)

RELEASE = date(2027, 3, 1)
IN_SEASON = date(2027, 3, 12)


def on(today: date) -> None:
    app.dependency_overrides[get_today] = lambda: today


def held_item(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
    shelf: str | None = "C1",
) -> str:
    """An item approved in November and held until March, on a shelf unless told otherwise."""
    item_id = sent_item(client)
    row = item_row(session, item_id)
    row.release_month = RELEASE
    session.add(row)
    session.commit()
    assert store(manager, item_id).status_code == 200
    page = approve(manager, item_id).json()
    assert page["status"] == "held_for_season"
    if shelf:
        assert store(manager, item_id, location_code=shelf).status_code == 200
    return item_id


def queue(manager: TestClient) -> dict[str, list[dict[str, Any]]]:  # noqa: F811
    response = manager.get("/approvals")
    assert response.status_code == 200, response.text
    return response.json()


def ids(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["item_id"] for entry in entries]


def history(page: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
    return [(entry["decision"], entry["reason"], entry["note"]) for entry in page["history"]]


def listings_on_channels(session: Session, item_id: str) -> list[Listing]:
    return list(session.exec(select(Listing).where(Listing.item_id == UUID(item_id))).all())


def test_a_held_item_waits_in_the_held_list_until_its_release_month(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)

    lists = queue(manager)
    assert ids(lists["held_for_season"]) == [item_id]
    assert lists["held_for_season"][0]["release_month"] == RELEASE.isoformat()
    assert lists["held_for_season"][0]["location_code"] == "C1"
    assert lists["awaiting_approval"] == []
    page = review(manager, item_id)
    assert page["back_for_review"] is False
    assert page["approved_by_name"] is not None

    # Nothing about its listing can change while it is held, short of List now.
    assert approve(manager, item_id).status_code == 409
    price = manager.put(
        f"/items/{item_id}/listings/channel_a/price", json={"price_override_cents": 5000}
    )
    assert price.status_code == 409
    reject = manager.post(f"/items/{item_id}/reject", json={"reason": "Too late"})
    assert reject.status_code == 409
    assert manager.post(f"/items/{item_id}/fresh-comps").status_code == 409


def test_a_held_item_comes_back_for_review_in_its_release_month_and_isnt_listed(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    on(IN_SEASON)

    lists = queue(manager)
    assert ids(lists["awaiting_approval"]) == [item_id]
    entry = lists["awaiting_approval"][0]
    assert entry["back_for_review"] is True
    assert entry["status"] == "held_for_season"
    assert entry["waiting_since"] == "2027-03-01T00:00:00Z"
    assert lists["held_for_season"] == []
    page = review(manager, item_id)
    assert page["back_for_review"] is True
    assert page["blockers"] == []
    # Reading it there publishes nothing, so a price approved months ago never goes up on its own.
    assert listings_on_channels(session, item_id) == []


def test_a_held_item_with_no_shelf_comes_back_for_review_rather_than_storage(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session, shelf=None)
    assert ids(queue(manager)["awaiting_storage"]) == [item_id]
    on(IN_SEASON)

    lists = queue(manager)
    assert ids(lists["awaiting_approval"]) == [item_id]
    assert lists["awaiting_storage"] == []

    page = approve(manager, item_id).json()
    assert page["status"] == "approved"
    assert listings_on_channels(session, item_id) == []
    assert ids(queue(manager)["awaiting_storage"]) == [item_id]
    page = store(manager, item_id, location_code="C2").json()
    assert [listing["channel_status"] for listing in page["listings"]] == ["pending", "pending"]


def test_fresh_comps_are_looked_up_again_beside_the_approved_price(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    on(IN_SEASON)
    # Months have passed, so the cached search is old and the lookup searches eBay again.
    for row in session.exec(select(CompSearch)).all():
        row.fetched_at = datetime.now(UTC) - timedelta(days=90)
        session.add(row)
    session.commit()
    search: StubSearch = use_search(serpapi_fixture("carhartt-detroit-jacket"))
    before = review(manager, item_id)
    assert before["fresh_appraisal"] is None

    page = manager.post(f"/items/{item_id}/fresh-comps").json()

    assert len(search.calls) >= 1
    fresh = page["fresh_appraisal"]
    assert fresh is not None
    assert fresh["comps"]
    assert fresh["price_typical_cents"] is not None
    # The listing keeps the price the manager approved until someone changes it.
    assert [listing["price_cents"] for listing in page["listings"]] == [
        listing["price_cents"] for listing in before["listings"]
    ]
    assert fresh["id"] != page["appraisal"]["id"]

    # Asking again shows the same lookup rather than spending another search.
    calls = len(search.calls)
    again = manager.post(f"/items/{item_id}/fresh-comps").json()
    assert again["fresh_appraisal"]["id"] == fresh["id"]
    assert len(search.calls) == calls
    assert review(manager, item_id)["fresh_appraisal"]["id"] == fresh["id"]
    count = session.exec(select(Appraisal).where(Appraisal.item_id == UUID(item_id))).all()
    assert len(count) == 2


def test_approving_a_held_item_as_it_is_lists_it_at_the_approved_price(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    approved = review(manager, item_id)["listings"]
    on(IN_SEASON)

    page = approve(manager, item_id).json()

    assert page["status"] == "approved"
    assert page["back_for_review"] is False
    assert [listing["channel_status"] for listing in page["listings"]] == ["pending", "pending"]
    prices = {
        listing.channel.value: listing.price_cents
        for listing in listings_on_channels(session, item_id)
    }
    assert prices == {listing["channel"]: listing["price_cents"] for listing in approved}
    a, b = (f"${listing['price_cents'] / 100:,.2f}" for listing in approved)
    assert history(page)[1:] == [
        ("yes", "Approved and held for its season until March 2027", None),
        ("yes", f"Approved again in its season at {a} on Channel A and {b} on Channel B", None),
    ]
    assert history(page)[0][0] == "yes"
    assert queue(manager)["awaiting_approval"] == []


def test_a_held_item_can_be_repriced_before_it_is_approved_again(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    on(IN_SEASON)

    response = manager.put(
        f"/items/{item_id}/listings/channel_a/price", json={"price_override_cents": 6250}
    )
    assert response.status_code == 200, response.text
    assert response.json()["listings"][0]["price_cents"] == 6250
    # The new price isn't listed until the manager approves it.
    assert listings_on_channels(session, item_id) == []

    page = approve(manager, item_id).json()
    channel_a = next(
        row for row in listings_on_channels(session, item_id) if row.channel.value == "channel_a"
    )
    assert channel_a.price_cents == 6250
    assert (history(page)[-1][1] or "").startswith(
        "Approved again in its season at $62.50 on Channel A"
    )


def test_a_held_item_back_for_review_can_be_declined(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    on(IN_SEASON)

    response = manager.post(
        f"/items/{item_id}/reject", json={"reason": "Sells for less now", "note": "Comps fell."}
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["status"] == "declined"
    assert [listing["state"] for listing in page["listings"]] == ["rejected", "rejected"]
    assert history(page)[-1] == ("no", "Sells for less now", "Comps fell.")
    assert listings_on_channels(session, item_id) == []
    assert queue(manager)["awaiting_approval"] == []


def test_list_now_sends_a_held_item_into_the_same_review_early(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    assert client.post(f"/items/{item_id}/list-now").status_code == 403

    response = manager.post(f"/items/{item_id}/list-now")

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["back_for_review"] is True
    assert page["status"] == "held_for_season"
    assert page["release_month"] == TODAY.replace(day=1).isoformat()
    assert history(page)[-1] == (
        "yes",
        "Sent for review before its release month of March 2027",
        None,
    )
    assert listings_on_channels(session, item_id) == []
    lists = queue(manager)
    assert ids(lists["awaiting_approval"]) == [item_id]
    assert lists["held_for_season"] == []
    # Asking twice records it once.
    assert len(history(manager.post(f"/items/{item_id}/list-now").json())) == len(history(page))

    assert manager.post(f"/items/{item_id}/fresh-comps").status_code == 200
    page = approve(manager, item_id).json()
    assert page["status"] == "approved"
    assert [listing["channel_status"] for listing in page["listings"]] == ["pending", "pending"]


def test_a_manager_can_take_a_held_item_out_of_online_selling_with_a_note(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    note = {"note": "Putting it on the store floor for the winter sale."}
    assert client.post(f"/items/{item_id}/not-online", json=note).status_code == 403
    assert manager.post(f"/items/{item_id}/not-online", json={"note": "  "}).status_code == 422
    assert manager.post(f"/items/{item_id}/not-online", json={}).status_code == 422

    response = manager.post(f"/items/{item_id}/not-online", json=note)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "not_listed_online"
    assert result["note"] == note["note"]
    assert result["decided_by_name"]
    assert item_row(session, item_id).status is ItemStatus.NOT_LISTED_ONLINE
    page = review(manager, item_id)
    assert history(page)[-1] == ("no", "Not listed online", note["note"])
    assert page["history"][-1]["decided_by_name"] == result["decided_by_name"]
    lists = queue(manager)
    assert ids(lists["not_listed_online"]) == [item_id]
    assert all(lists[name] == [] for name in lists if name != "not_listed_online")

    # It stays out, even once its season comes, until a manager puts it back for review.
    on(IN_SEASON)
    assert queue(manager)["awaiting_approval"] == []
    assert approve(manager, item_id).status_code == 409
    assert manager.post(f"/items/{item_id}/list-now").status_code == 409
    assert manager.post(f"/items/{item_id}/not-online", json=note).status_code == 409


def test_staff_can_skip_online_selling_where_the_hold_hint_shows(
    client: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = listed_item(client)

    response = client.post(f"/items/{item_id}/not-online", json={"note": "Floor sale instead."})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "not_listed_online"
    # The listing can't be written or decided on again once it's out of online selling.
    assert (
        client.post(f"/items/{item_id}/drafts", json={"channels": ["channel_a"]}).status_code == 409
    )
    rows = session.exec(select(Appraisal.id).where(col(Appraisal.item_id) == UUID(item_id))).all()
    retry = client.post(
        f"/items/{item_id}/decisions", json={"appraisal_id": str(rows[0]), "decision": "yes"}
    )
    assert retry.status_code == 409


def test_a_manager_can_skip_online_selling_from_the_review_before_approving(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = sent_item(client)
    row = item_row(session, item_id)
    row.release_month = RELEASE
    session.add(row)
    session.commit()
    store(manager, item_id, **PACKAGE)

    response = manager.post(f"/items/{item_id}/not-online", json={"note": "Too bulky to hold."})

    assert response.status_code == 200, response.text
    assert queue(manager)["awaiting_approval"] == []
    assert approve(manager, item_id).status_code == 409


def test_only_an_item_staff_said_yes_to_can_be_taken_out_of_online_selling(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    on(IN_SEASON)
    approve(manager, item_id)
    response = manager.post(f"/items/{item_id}/not-online", json={"note": "Too late."})
    assert response.status_code == 409
