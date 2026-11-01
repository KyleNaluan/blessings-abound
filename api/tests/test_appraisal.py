"""The photo-to-decision path through the API, run against real Postgres."""

import base64
import io
import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app.ai import Message
from app.appraisal import get_photo_storage, get_vision_providers
from app.auth import AuthUnavailableError, get_token_verifier
from app.db import get_session
from app.main import app
from app.models import (
    Appraisal,
    Category,
    Condition,
    Confidence,
    Decision,
    Item,
    ItemCard,
    ItemStatus,
    Profile,
    Role,
)
from app.settings import get_settings
from app.storage import LocalStorage

STAFF_TOKEN = "staff-token"
OTHER_STAFF_TOKEN = "other-staff-token"
MANAGER_TOKEN = "manager-token"
UNKNOWN_USER_TOKEN = "no-profile-token"
INACTIVE_TOKEN = "inactive-token"


MODEL_CARD = {
    "category": "apparel",
    "brand": "Carhartt",
    "product": "canvas jacket",
    "visible_text": "Carhartt",
    "search_query": "Carhartt canvas jacket",
    "model_confidence": "high",
    "color": "brown",
    "material": "canvas",
    "exact_model": None,
    "platform": None,
}


def jpeg(size: tuple[int, int] = (20, 10)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, "brown").save(output, format="JPEG")
    return output.getvalue()


class StubChat:
    """Answers with each reply in turn and repeats the last, where an int is an HTTP error."""

    def __init__(self, *replies: str | int, name: str = "primary") -> None:
        self.name = name
        self.replies = list(replies)
        self.calls: list[list[Message]] = []
        self.on_call: Callable[[], None] | None = None

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        self.calls.append(messages)
        if self.on_call:
            self.on_call()
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, int):
            request = httpx2.Request("POST", "https://stub.example.com")
            response = httpx2.Response(reply, request=request)
            raise httpx2.HTTPStatusError("stubbed", request=request, response=response)
        return reply


def use_model(*providers: StubChat) -> None:
    app.dependency_overrides[get_vision_providers] = lambda: list(providers)


def model_replies(**changes: Any) -> StubChat:
    chat = StubChat(json.dumps(MODEL_CARD | changes))
    use_model(chat)
    return chat


class StubVerifier:
    def __init__(self, tokens: dict[str, UUID]) -> None:
        self.tokens = tokens

    def user_id(self, token: str) -> UUID | None:
        return self.tokens.get(token)


class UnavailableVerifier:
    def user_id(self, token: str) -> UUID | None:
        raise AuthUnavailableError


def add_profile(session: Session, username: str, role: Role = Role.STAFF, **values: Any) -> UUID:
    profile = Profile(
        auth_user_id=uuid4(), username=username, display_name=username.title(), role=role, **values
    )
    session.add(profile)
    session.commit()
    return profile.auth_user_id


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path)


@pytest.fixture
def client(session: Session, storage: LocalStorage) -> Iterator[TestClient]:
    tokens = {
        STAFF_TOKEN: add_profile(session, "staff1"),
        OTHER_STAFF_TOKEN: add_profile(session, "staff2"),
        MANAGER_TOKEN: add_profile(session, "manager1", Role.MANAGER),
        INACTIVE_TOKEN: add_profile(session, "gone1", is_active=False),
        UNKNOWN_USER_TOKEN: uuid4(),
    }
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_photo_storage] = lambda: storage
    app.dependency_overrides[get_token_verifier] = lambda: StubVerifier(tokens)
    model_replies()
    yield TestClient(app, headers={"Authorization": f"Bearer {STAFF_TOKEN}"})
    app.dependency_overrides.clear()


def as_token(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def upload(client: TestClient, content: bytes | None = None) -> dict[str, Any]:
    content = jpeg() if content is None else content
    response = client.post(
        "/items", files={"photo": ("item.jpg", content, "image/jpeg")}, headers=client.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_card(client: TestClient, item_id: str) -> dict[str, Any]:
    response = client.post(f"/items/{item_id}/card", json={"condition": "pre_owned"})
    assert response.status_code == 200, response.text
    return response.json()


def appraise(client: TestClient, item_id: str) -> dict[str, Any]:
    response = client.post(f"/items/{item_id}/appraisals")
    assert response.status_code == 200, response.text
    return response.json()


def appraised_item(client: TestClient) -> tuple[str, str]:
    item_id = upload(client)["id"]
    add_card(client, item_id)
    return item_id, appraise(client, item_id)["id"]


def decide(client: TestClient, item_id: str, appraisal_id: str, choice: str = "yes") -> Any:
    return client.post(
        f"/items/{item_id}/decisions", json={"appraisal_id": appraisal_id, "decision": choice}
    )


def test_the_whole_path_saves_a_decision_and_lists_it(client: TestClient, session: Session) -> None:
    item = upload(client)
    assert item["status"] == "intake"

    card = add_card(client, item["id"])
    assert card["item_id"] == item["id"]
    assert card["condition"] == "pre_owned"

    appraisal = appraise(client, item["id"])
    assert appraisal["price_low_cents"] <= appraisal["price_typical_cents"]
    assert appraisal["price_typical_cents"] <= appraisal["price_high_cents"]

    response = decide(client, item["id"], appraisal["id"])
    assert response.status_code == 201, response.text
    decision = response.json()

    saved = session.get(Decision, UUID(decision["id"]))
    assert saved is not None
    assert saved.decision == "yes"

    recent = client.get("/decisions").json()
    assert [row["id"] for row in recent] == [decision["id"]]
    assert recent[0]["sku"] == item["sku"]
    assert recent[0]["product"] == card["product"]
    assert recent[0]["price_typical_cents"] == appraisal["price_typical_cents"]
    assert recent[0]["decided_by_name"] == "Staff1"
    assert datetime.fromisoformat(recent[0]["decided_at"]).utcoffset() is not None


def test_upload_stores_the_photo_and_records_who_listed_it(
    client: TestClient, session: Session, storage: LocalStorage
) -> None:
    item = upload(client, b"the photo bytes")
    assert storage.read(item["photo_keys"][0]) == b"the photo bytes"
    row = session.get(Item, UUID(item["id"]))
    assert row is not None
    lister = session.get(Profile, row.lister_id)
    assert lister is not None
    assert lister.username == "staff1"


def test_upload_needs_a_photo(client: TestClient) -> None:
    assert client.post("/items").status_code == 422


def test_upload_refuses_an_empty_photo(client: TestClient) -> None:
    response = client.post("/items", files={"photo": ("item.jpg", b"", "image/jpeg")})
    assert response.status_code == 422


def test_card_keeps_what_staff_entered(client: TestClient) -> None:
    item_id = upload(client)["id"]
    response = client.post(
        f"/items/{item_id}/card",
        json={"condition": "new_with_tags", "department": "kids", "flaws": ["stains"]},
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["condition"] == "new_with_tags"
    assert card["department"] == "kids"
    assert card["flaws"] == ["stains"]


def test_card_refuses_an_unknown_condition(client: TestClient) -> None:
    item_id = upload(client)["id"]
    response = client.post(f"/items/{item_id}/card", json={"condition": "fine"})
    assert response.status_code == 422


def test_asking_for_a_card_again_returns_the_same_card(
    client: TestClient, session: Session
) -> None:
    item_id = upload(client)["id"]
    assert add_card(client, item_id) == add_card(client, item_id)
    row = session.get(Item, UUID(item_id))
    assert row is not None
    assert row.status == ItemStatus.CARD_READY


def test_each_step_after_upload_needs_an_item_that_exists(client: TestClient) -> None:
    missing = uuid4()
    assert client.post(f"/items/{missing}/card", json={"condition": "pre_owned"}).status_code == 404
    assert client.post(f"/items/{missing}/appraisals").status_code == 404
    assert decide(client, str(missing), str(uuid4())).status_code == 404


def test_appraising_needs_a_card_first(client: TestClient) -> None:
    item_id = upload(client)["id"]
    assert client.post(f"/items/{item_id}/appraisals").status_code == 409


def test_appraising_again_keeps_both_appraisals(client: TestClient, session: Session) -> None:
    item_id = upload(client)["id"]
    add_card(client, item_id)
    first, second = appraise(client, item_id), appraise(client, item_id)
    assert first["id"] != second["id"]
    rows = session.exec(select(Appraisal).where(Appraisal.item_id == UUID(item_id))).all()
    assert len(rows) == 2


def test_deciding_needs_an_appraisal_first(client: TestClient) -> None:
    item_id = upload(client)["id"]
    add_card(client, item_id)
    assert decide(client, item_id, str(uuid4())).status_code == 409


def test_a_decision_cannot_use_another_items_appraisal(client: TestClient) -> None:
    item_id, _ = appraised_item(client)
    _, other_appraisal = appraised_item(client)
    assert decide(client, item_id, other_appraisal).status_code == 404


def test_a_decision_must_be_yes_or_no(client: TestClient) -> None:
    item_id, appraisal_id = appraised_item(client)
    assert decide(client, item_id, appraisal_id, "maybe").status_code == 422


@pytest.mark.parametrize(
    ("choice", "status"), [("yes", ItemStatus.APPRAISED), ("no", ItemStatus.DECLINED)]
)
def test_a_decision_sets_the_item_status(
    client: TestClient, session: Session, choice: str, status: ItemStatus
) -> None:
    item_id, appraisal_id = appraised_item(client)
    assert decide(client, item_id, appraisal_id, choice).status_code == 201
    row = session.get(Item, UUID(item_id))
    assert row is not None
    assert row.status == status


def test_decisions_are_kept_as_a_history(client: TestClient, session: Session) -> None:
    item_id, appraisal_id = appraised_item(client)
    assert decide(client, item_id, appraisal_id, "no").status_code == 201
    assert decide(client, item_id, appraisal_id, "yes").status_code == 201
    rows = session.exec(select(Decision).where(Decision.item_id == UUID(item_id))).all()
    assert sorted(row.decision for row in rows) == ["no", "yes"]
    row = session.get(Item, UUID(item_id))
    assert row is not None
    assert row.status == ItemStatus.APPRAISED


def test_an_item_past_the_decision_cannot_be_decided_again(
    client: TestClient, session: Session
) -> None:
    item_id, appraisal_id = appraised_item(client)
    row = session.get(Item, UUID(item_id))
    assert row is not None
    row.status = ItemStatus.LISTED
    session.add(row)
    session.commit()
    assert decide(client, item_id, appraisal_id).status_code == 409


def test_staff_see_their_own_decisions_and_managers_see_all(client: TestClient) -> None:
    item_id, appraisal_id = appraised_item(client)
    assert decide(client, item_id, appraisal_id).status_code == 201
    other = TestClient(app, headers=as_token(OTHER_STAFF_TOKEN))
    item_id, appraisal_id = appraised_item(other)
    assert decide(other, item_id, appraisal_id).status_code == 201

    names = {row["decided_by_name"] for row in client.get("/decisions").json()}
    assert names == {"Staff1"}
    names = {row["decided_by_name"] for row in other.get("/decisions").json()}
    assert names == {"Staff2"}
    manager = client.get("/decisions", headers=as_token(MANAGER_TOKEN)).json()
    assert {row["decided_by_name"] for row in manager} == {"Staff1", "Staff2"}


def test_recent_decisions_are_newest_first_and_limited(
    client: TestClient, session: Session
) -> None:
    item_id, appraisal_id = appraised_item(client)
    person = session.exec(select(Profile).where(Profile.username == "staff1")).one()
    days = [2, 1, 3]
    for day in days:
        session.add(
            Decision(
                item_id=UUID(item_id),
                appraisal_id=UUID(appraisal_id),
                decision="yes",  # type: ignore[arg-type]
                decided_by=person.auth_user_id,
                decided_at=datetime(2026, 11, day, tzinfo=UTC),
                note=str(day),
            )
        )
    session.commit()
    rows = client.get("/decisions", params={"limit": 2}).json()
    assert [datetime.fromisoformat(row["decided_at"]).day for row in rows] == [3, 2]


@pytest.mark.parametrize("limit", [0, 101])
def test_the_decision_list_limit_is_bounded(client: TestClient, limit: int) -> None:
    assert client.get("/decisions", params={"limit": limit}).status_code == 422


def test_the_card_comes_from_the_model_with_the_photo_and_staff_entries(
    client: TestClient,
) -> None:
    chat = model_replies()
    item_id = upload(client, jpeg((2000, 1000)))["id"]
    response = client.post(
        f"/items/{item_id}/card",
        json={"condition": "pre_owned", "department": "mens", "size": "L", "flaws": ["stains"]},
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["brand"] == "Carhartt"
    assert card["search_query"] == "Carhartt canvas jacket"
    assert card["color"] == "brown"
    assert card["model_confidence"] == "high"
    assert card["staff_confirmed"] is False
    assert card["needs_confirmation"] is False

    (messages,) = chat.calls
    text, image = messages[0]["content"]
    assert "condition: pre_owned" in text["text"]
    assert "department: mens" in text["text"]
    assert "flaws: ['stains']" in text["text"]
    encoded = image["image_url"]["url"].removeprefix("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(encoded))) as sent:
        assert sent.format == "JPEG"
        assert sent.size == (960, 480)


def test_staff_fields_from_the_model_are_dropped(client: TestClient) -> None:
    model_replies(
        condition="new_with_tags",
        department="womens",
        size="XS",
        size_type="petite",
        flaws=["tears"],
        tested_working=True,
        complete_in_box=True,
        accessories_included="charger",
    )
    item_id = upload(client)["id"]
    response = client.post(
        f"/items/{item_id}/card", json={"condition": "pre_owned", "department": "kids"}
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["condition"] == "pre_owned"
    assert card["department"] == "kids"
    assert card["size"] is None
    assert card["size_type"] is None
    assert card["flaws"] == []
    assert card["tested_working"] is None
    assert card["complete_in_box"] is None
    assert card["accessories_included"] is None


def test_a_bad_reply_is_retried_on_the_same_model(client: TestClient) -> None:
    chat = StubChat("not json", json.dumps(MODEL_CARD))
    use_model(chat)
    assert add_card(client, upload(client)["id"])["brand"] == "Carhartt"
    assert len(chat.calls) == 2


def test_the_fallback_takes_over_when_the_first_model_fails(client: TestClient) -> None:
    primary = StubChat(429)
    fallback = StubChat(json.dumps(MODEL_CARD | {"brand": "Dickies"}), name="fallback")
    use_model(primary, fallback)
    assert add_card(client, upload(client)["id"])["brand"] == "Dickies"
    assert len(primary.calls) == 1


def test_when_every_model_fails_the_item_can_try_again(
    client: TestClient, session: Session
) -> None:
    use_model(StubChat("nope"), StubChat(500, name="fallback"))
    item_id = upload(client)["id"]
    response = client.post(f"/items/{item_id}/card", json={"condition": "pre_owned"})
    assert response.status_code == 502
    assert "Try again" in response.json()["detail"]
    row = session.get(Item, UUID(item_id))
    assert row is not None
    assert row.status == ItemStatus.INTAKE

    model_replies()
    assert add_card(client, item_id)["brand"] == "Carhartt"


def test_a_model_that_is_not_set_up_is_a_clear_error(client: TestClient) -> None:
    use_model()
    item_id = upload(client)["id"]
    response = client.post(f"/items/{item_id}/card", json={"condition": "pre_owned"})
    assert response.status_code == 503


def test_a_photo_that_is_not_an_image_is_refused(client: TestClient) -> None:
    chat = model_replies()
    item_id = upload(client, b"not an image")["id"]
    response = client.post(f"/items/{item_id}/card", json={"condition": "pre_owned"})
    assert response.status_code == 422
    assert chat.calls == []


def test_a_card_already_made_does_not_call_the_model_again(client: TestClient) -> None:
    chat = model_replies()
    item_id = upload(client)["id"]
    add_card(client, item_id)
    use_model()
    add_card(client, item_id)
    assert len(chat.calls) == 1


def test_a_request_that_finishes_second_keeps_the_first_card(
    client: TestClient, session: Session
) -> None:
    chat = model_replies()
    item_id = upload(client)["id"]

    def other_request_finishes() -> None:
        row = session.get(Item, UUID(item_id))
        assert row is not None
        row.status = ItemStatus.CARD_READY
        session.add(row)
        session.add(
            ItemCard(
                item_id=UUID(item_id),
                category=Category.APPAREL,
                brand="First",
                search_query="first",
                model_confidence=Confidence.HIGH,
                condition=Condition.PRE_OWNED,
            )
        )
        session.commit()

    chat.on_call = other_request_finishes
    assert add_card(client, item_id)["brand"] == "First"


@pytest.mark.parametrize(
    "changes", [{"model_confidence": "low"}, {"brand": None, "model_confidence": "high"}]
)
def test_an_unsure_card_stops_the_search_until_staff_confirm(
    client: TestClient, session: Session, changes: dict[str, Any]
) -> None:
    model_replies(**changes)
    item_id = upload(client)["id"]
    assert add_card(client, item_id)["needs_confirmation"] is True

    refused = client.post(f"/items/{item_id}/appraisals")
    assert refused.status_code == 409
    assert "Confirm the brand and model" in refused.json()["detail"]
    assert session.exec(select(Appraisal)).all() == []

    confirmed = client.patch(f"/items/{item_id}/card", json={})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["needs_confirmation"] is False
    assert confirmed.json()["staff_confirmed"] is True
    assert confirmed.json()["staff_edited"] is False
    appraise(client, item_id)


def test_the_confidence_bar_is_a_setting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "item_card_min_confidence", Confidence.HIGH)
    model_replies(model_confidence="medium")
    item_id = upload(client)["id"]
    assert add_card(client, item_id)["needs_confirmation"] is True
    assert client.post(f"/items/{item_id}/appraisals").status_code == 409


def test_staff_can_edit_the_card_and_clear_a_proposal(client: TestClient) -> None:
    item_id = upload(client)["id"]
    add_card(client, item_id)
    response = client.patch(
        f"/items/{item_id}/card",
        json={
            "brand": " Dickies ",
            "search_query": "Dickies canvas jacket",
            "color": "",
            "exact_model": "Eisenhower",
            "condition": "new_without_tags",
            "flaws": ["scuffs"],
        },
    )
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["brand"] == "Dickies"
    assert card["search_query"] == "Dickies canvas jacket"
    assert card["color"] is None
    assert card["exact_model"] == "Eisenhower"
    assert card["condition"] == "new_without_tags"
    assert card["flaws"] == ["scuffs"]
    assert card["material"] == "canvas"
    assert card["staff_edited"] is True
    assert card["staff_confirmed"] is True


def test_sending_the_same_values_is_not_an_edit(client: TestClient) -> None:
    item_id = upload(client)["id"]
    card = add_card(client, item_id)
    response = client.patch(
        f"/items/{item_id}/card",
        json={"brand": card["brand"], "category": card["category"], "flaws": []},
    )
    assert response.json()["staff_edited"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"search_query": "   "},
        {"search_query": None},
        {"category": None},
        {"condition": None},
        {"flaws": None},
        {"model_confidence": "high"},
        {"staff_confirmed": False},
    ],
)
def test_an_edit_cannot_empty_a_required_field_or_set_the_models_own(
    client: TestClient, body: dict[str, Any]
) -> None:
    item_id = upload(client)["id"]
    add_card(client, item_id)
    assert client.patch(f"/items/{item_id}/card", json=body).status_code == 422


def test_editing_needs_a_card_and_an_item_still_being_appraised(
    client: TestClient, session: Session
) -> None:
    assert client.patch(f"/items/{uuid4()}/card", json={}).status_code == 404
    item_id = upload(client)["id"]
    assert client.patch(f"/items/{item_id}/card", json={}).status_code == 409
    add_card(client, item_id)
    row = session.get(Item, UUID(item_id))
    assert row is not None
    row.status = ItemStatus.LISTED
    session.add(row)
    session.commit()
    assert client.patch(f"/items/{item_id}/card", json={}).status_code == 409


ROUTES = [
    ("post", "/items"),
    ("post", f"/items/{uuid4()}/card"),
    ("patch", f"/items/{uuid4()}/card"),
    ("post", f"/items/{uuid4()}/appraisals"),
    ("post", f"/items/{uuid4()}/decisions"),
    ("get", "/decisions"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_step_needs_a_sign_in(client: TestClient, method: str, path: str) -> None:
    anonymous = TestClient(app)
    assert anonymous.request(method, path).status_code == 401
    bad = anonymous.request(method, path, headers=as_token("nonsense"))
    assert bad.status_code == 401


@pytest.mark.parametrize("token", [UNKNOWN_USER_TOKEN, INACTIVE_TOKEN])
def test_a_person_without_an_active_profile_is_refused(client: TestClient, token: str) -> None:
    assert client.get("/decisions", headers=as_token(token)).status_code == 403


def test_a_sign_in_that_cannot_be_checked_is_not_taken_as_good(client: TestClient) -> None:
    app.dependency_overrides[get_token_verifier] = UnavailableVerifier
    assert client.get("/decisions").status_code == 503
