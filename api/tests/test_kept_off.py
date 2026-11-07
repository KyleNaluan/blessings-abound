"""Putting an item kept off online back for review, and warning at intake when one comes back in."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Appraisal, ItemCard, ItemStatus
from tests.test_appraisal import TODAY, add_card, jpeg, listed_item, upload, write_drafts
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
from tests.test_season_return import (
    IN_SEASON,
    RELEASE,
    held_item,
    history,
    ids,
    listings_on_channels,
    on,
    queue,
)

NOTE = {"note": "Selling it on the store floor."}
BACK = {"note": "A customer asked for it online."}
THIS_MONTH = TODAY.replace(day=1)


def keep_off(by: TestClient, item_id: str, note: str = NOTE["note"]) -> dict[str, Any]:
    response = by.post(f"/items/{item_id}/not-online", json={"note": note})
    assert response.status_code == 200, response.text
    return response.json()


def put_back(manager: TestClient, item_id: str) -> dict[str, Any]:  # noqa: F811
    response = manager.post(f"/items/{item_id}/put-back", json=BACK)
    assert response.status_code == 200, response.text
    return response.json()


def matches(client: TestClient, item_id: str) -> list[dict[str, Any]]:  # noqa: F811
    response = client.get(f"/items/{item_id}/kept-off-matches")
    assert response.status_code == 200, response.text
    return response.json()


def test_only_a_manager_can_put_an_item_back_and_it_needs_a_note(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    assert manager.post(f"/items/{item_id}/put-back", json=BACK).status_code == 409
    keep_off(manager, item_id)

    assert client.post(f"/items/{item_id}/put-back", json=BACK).status_code == 403
    assert manager.post(f"/items/{item_id}/put-back", json={"note": " "}).status_code == 422
    assert manager.post(f"/items/{item_id}/put-back", json={}).status_code == 422
    assert manager.post(f"/items/{item_id}/put-back", json={"note": "x" * 201}).status_code == 422
    assert item_row(session, item_id).status is ItemStatus.NOT_LISTED_ONLINE


def test_a_held_item_put_back_comes_to_review_with_fresh_comps_before_it_is_listed(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    keep_off(manager, item_id)

    page = put_back(manager, item_id)

    assert page["status"] == "held_for_season"
    assert page["release_month"] == THIS_MONTH.isoformat()
    assert page["back_for_review"] is True
    assert page["put_back"] is True
    assert history(page)[-2:] == [
        ("no", "Not listed online", NOTE["note"]),
        ("yes", "Put back for review", BACK["note"]),
    ]
    lists = queue(manager)
    assert ids(lists["awaiting_approval"]) == [item_id]
    entry = lists["awaiting_approval"][0]
    assert entry["put_back"] is True
    assert entry["channels"] == ["channel_a", "channel_b"]
    assert entry["waiting_since"] == page["history"][-1]["decided_at"].replace("+00:00", "Z")
    assert lists["not_listed_online"] == []
    assert lists["held_for_season"] == []
    # Nothing goes up until a manager has looked at it again.
    assert listings_on_channels(session, item_id) == []
    assert manager.post(f"/items/{item_id}/put-back", json=BACK).status_code == 409

    fresh = manager.post(f"/items/{item_id}/fresh-comps").json()["fresh_appraisal"]
    assert fresh is not None
    approved = approve(manager, item_id).json()

    assert approved["status"] == "approved"
    assert approved["put_back"] is False
    assert [listing["channel_status"] for listing in approved["listings"]] == [
        "pending",
        "pending",
    ]
    assert (history(approved)[-1][1] or "").startswith("Approved again in its season at ")


def test_putting_an_item_back_months_later_looks_its_comps_up_again(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = held_item(client, manager, session)
    on(IN_SEASON)
    first = manager.post(f"/items/{item_id}/fresh-comps").json()["fresh_appraisal"]
    keep_off(manager, item_id)
    on(date(2027, 9, 14))

    page = put_back(manager, item_id)

    assert page["release_month"] == "2027-09-01"
    # The lookup from March is too old to price it by in September.
    assert page["fresh_appraisal"] is None
    again = manager.post(f"/items/{item_id}/fresh-comps").json()["fresh_appraisal"]
    assert again["id"] != first["id"]
    rows = session.exec(select(Appraisal).where(Appraisal.item_id == UUID(item_id))).all()
    assert len(rows) == 3


def test_an_item_kept_off_before_approval_goes_back_to_waiting_for_approval(
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
    keep_off(manager, item_id)

    page = put_back(manager, item_id)

    assert page["status"] == "appraised"
    assert page["put_back"] is True
    assert page["back_for_review"] is False
    assert page["blockers"] == []
    assert [listing["state"] for listing in page["listings"]] == [
        "awaiting_approval",
        "awaiting_approval",
    ]
    entry = queue(manager)["awaiting_approval"][0]
    assert (entry["item_id"], entry["put_back"]) == (item_id, True)

    # The normal approval follows, which holds it until its season as before.
    approved = approve(manager, item_id).json()
    assert approved["status"] == "held_for_season"
    assert approved["put_back"] is False
    assert ids(queue(manager)["held_for_season"]) == [item_id]


def test_an_item_kept_off_before_its_listing_was_written_comes_back_to_be_written(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = listed_item(client)
    keep_off(client, item_id)

    page = put_back(manager, item_id)

    assert page["status"] == "appraised"
    assert page["listings"] == []
    assert page["blockers"] == ["Staff haven't sent this listing for approval yet."]
    entry = queue(manager)["awaiting_approval"][0]
    assert (entry["item_id"], entry["channels"], entry["put_back"]) == (item_id, [], True)
    assert approve(manager, item_id).status_code == 409

    # The manager writes and sends the listing from the review, then approves it as usual.
    write_drafts(manager, item_id)
    assert manager.post(f"/items/{item_id}/drafts/submit").status_code == 200
    store(manager, item_id, **PACKAGE)
    assert review(manager, item_id)["blockers"] == []
    assert approve(manager, item_id).json()["status"] == "approved"


def test_the_not_listed_online_list_says_who_kept_each_item_off_newest_first(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    older = listed_item(client)
    keep_off(client, older, "Bulky, so it stays in the store.")
    newer = held_item(client, manager, session)
    kept = keep_off(manager, newer)

    lists = queue(manager)

    assert ids(lists["not_listed_online"]) == [newer, older]
    entry = lists["not_listed_online"][0]
    assert entry["note"] == NOTE["note"]
    assert entry["decided_by_name"] == kept["decided_by_name"]
    assert entry["brand"] is not None
    assert lists["not_listed_online"][1]["note"] == "Bulky, so it stays in the store."
    assert client.get("/approvals").status_code == 403

    put_back(manager, newer)
    assert ids(queue(manager)["not_listed_online"]) == [older]


def test_intake_warns_about_an_item_kept_off_online_with_the_same_brand_and_product(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    earlier = listed_item(client)
    kept = keep_off(client, earlier)
    new = upload(client)["id"]
    # The new photo doesn't match, and the card isn't read yet.
    assert matches(client, new) == []
    add_card(client, new)
    card = session.get(ItemCard, UUID(new))
    assert card is not None and card.brand and card.product
    # Read with other capitals and spaces, which don't make it a different item.
    card.brand = f"  {card.brand.upper()} "
    card.product = card.product.lower()
    session.add(card)
    session.commit()

    found = matches(client, new)

    assert [(m["item_id"], m["matched_on"]) for m in found] == [(earlier, "brand_and_product")]
    assert found[0]["note"] == NOTE["note"]
    assert found[0]["decided_by_name"] == kept["decided_by_name"]
    assert found[0]["decided_at"].replace("Z", "+00:00") == kept["decided_at"].replace(
        "Z", "+00:00"
    )
    assert matches(client, earlier) == []

    # A different product is a different item.
    card.product = "Something else"
    session.add(card)
    session.commit()
    assert matches(client, new) == []


def test_a_shared_photo_matches_before_the_card_is_read_until_the_item_is_put_back(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    photo = jpeg()
    earlier = upload(client, photo)["id"]
    add_card(client, earlier)
    appraisal = client.post(f"/items/{earlier}/appraisals").json()
    decided = client.post(
        f"/items/{earlier}/decisions", json={"appraisal_id": appraisal["id"], "decision": "yes"}
    )
    assert decided.status_code == 201
    keep_off(client, earlier)
    started = datetime.now(UTC)

    new = upload(client, photo)["id"]
    found = matches(client, new)

    assert [(m["item_id"], m["matched_on"]) for m in found] == [(earlier, "photo")]
    assert datetime.fromisoformat(found[0]["decided_at"].replace("Z", "+00:00")) < started

    put_back(manager, earlier)
    assert matches(client, new) == []
