from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.claims import ListingFacts, check_listing
from app.comps import parse_comps
from app.flag_explanations import FlagContext, parse_text, template_text
from app.flag_explanations import build_messages as build_flag_messages
from app.listing_drafts import build_messages, category_options, parse_draft
from app.models import Channel, Condition, ConflictKind, ItemCard, SyncEvent, SyncLogEntry
from app.offline_standin import ITEM_CARD, PASSWORD, USERS, app, closest_fixture
from app.supabase_auth import placeholder_email
from app.vision import ItemCardDraft

client = TestClient(app)
STAFF_EMAIL = placeholder_email("demo.staff")


def sign_in(password: str = PASSWORD, email: str = STAFF_EMAIL):
    return client.post(
        "/auth/v1/token",
        params={"grant_type": "password"},
        json={"email": email, "password": password},
    )


def test_a_demo_account_signs_in_and_its_token_names_it() -> None:
    session = sign_in().json()
    user = client.get(
        "/auth/v1/user", headers={"Authorization": f"Bearer {session['access_token']}"}
    ).json()
    assert UUID(user["id"]) == USERS["demo.staff"]
    assert user["email"] == STAFF_EMAIL


def test_a_wrong_password_gets_the_answer_auth_gives() -> None:
    response = sign_in("wrong")
    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_credentials"


def test_a_refresh_token_gives_a_new_session() -> None:
    refresh_token = sign_in().json()["refresh_token"]
    response = client.post(
        "/auth/v1/token",
        params={"grant_type": "refresh_token"},
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200


def test_a_token_that_is_not_one_is_refused() -> None:
    response = client.get("/auth/v1/user", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401


def test_photos_are_saved_and_read_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFLINE_PHOTO_DIR", str(tmp_path))
    assert client.post("/storage/v1/object/photos/a/b.jpg", content=b"photo").status_code == 200
    assert client.get("/storage/v1/object/photos/a/b.jpg").content == b"photo"
    assert client.get("/storage/v1/object/photos/a/other.jpg").status_code == 404


def test_the_fixed_card_is_one_the_app_accepts() -> None:
    ItemCardDraft.model_validate(ITEM_CARD)
    answer = client.post("/v1/chat/completions", json={}).json()
    assert answer["choices"][0]["message"]["content"]


@pytest.mark.parametrize(
    ("channel", "category"), [(Channel.CHANNEL_A, "Unisex Clothing"), (Channel.CHANNEL_B, "Unisex")]
)
def test_the_fixed_listing_passes_the_checker(channel: Channel, category: str) -> None:
    card = ItemCard(item_id=uuid4(), condition=Condition.PRE_OWNED, **ITEM_CARD)
    facts = ListingFacts.from_card(card)
    body = {"messages": build_messages(facts, channel)}
    answer = client.post("/v1/chat/completions", json=body).json()
    draft = parse_draft(
        answer["choices"][0]["message"]["content"], category_options(channel, card.category)
    )
    assert draft.category == category
    assert check_listing(draft.title, draft.description, facts) == []


def test_a_flag_gets_its_own_fixed_sentences_back() -> None:
    entry = SyncLogEntry(
        id=uuid4(),
        event=SyncEvent.FLAGGED,
        conflict=ConflictKind.UNKNOWN_LISTING,
        conflict_key="unknown_listing:channel_b:listing:1",
        channel=Channel.CHANNEL_B,
        message="Channel B has a live listing Turnstone has no record of.",
    )
    context = FlagContext(entry, title=None, sku=None, item_status=None)
    template = template_text(context)
    body = {"messages": build_flag_messages(context, template)}

    answer = client.post("/v1/chat/completions", json=body).json()

    assert parse_text(answer["choices"][0]["message"]["content"]) == template


def test_a_search_gets_the_closest_fixture_with_real_comps() -> None:
    assert closest_fixture("Nintendo Switch console", "3000")["search_parameters"]["_nkw"] == (
        "Nintendo Switch console"
    )
    # Nothing in common falls back to the item on the fixed card.
    assert "501" in closest_fixture("zzz", "3000")["search_parameters"]["_nkw"]
    response = client.get("/search.json", params={"_nkw": "Levi's 501", "LH_ItemCondition": "3000"})
    assert response.json()["search_metadata"]["status"] == "Success"
    assert parse_comps(response.json())
