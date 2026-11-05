"""The channel and timing recommendation: the rules, the reason, and the hold it sets."""

import json
import threading
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import channel_timing
from app.ai import Message
from app.appraisal import get_reason_providers
from app.channel_timing import (
    advise,
    channel_options,
    get_today,
    matching_season,
    month_span,
    release_month,
    template_reason,
    write_reason,
)
from app.claims import ListingFacts
from app.main import app
from app.models import (
    Category,
    Channel,
    Condition,
    DraftSource,
    FallbackReason,
    Item,
    ItemCard,
)
from app.store_settings import SeasonalCalendar, StoreSettings
from tests.test_appraisal import (
    REASON,
    TODAY,
    StubChat,
    listed_item,
    model_replies,
    use_drafter,
    use_reasoner,
    write_drafts,
)
from tests.test_approval import (  # noqa: F401, the fixtures these tests build on
    PACKAGE,
    approve,
    client,
    manager,
)

CALENDAR = StoreSettings().seasonal_calendar


def apparel(**values: Any) -> ListingFacts:
    return ListingFacts(category=Category.APPAREL, condition=Condition.PRE_OWNED, **values)


JACKET = apparel(brand="Carhartt", product="canvas jacket")
GAME = ListingFacts(
    category=Category.ELECTRONICS_GAMES,
    condition=Condition.PRE_OWNED,
    brand="Nintendo",
    product="Madden NFL football game",
)


def calendar(*seasons: dict[str, Any]) -> SeasonalCalendar:
    return SeasonalCalendar.model_validate({"seasons": list(seasons)})


def season(**values: Any) -> dict[str, Any]:
    return {
        "name": "Coats",
        "category": "apparel",
        "match_words": ["jacket"],
        "months": [3],
    } | values


def test_branded_apparel_can_go_on_both_channels() -> None:
    options = channel_options(JACKET)
    assert [(option.channel, option.takes, option.why_not) for option in options] == [
        (Channel.CHANNEL_A, True, None),
        (Channel.CHANNEL_B, True, None),
    ]


def test_a_game_can_go_on_channel_a_only() -> None:
    (a, b) = channel_options(GAME)
    assert a.takes
    assert not b.takes
    assert b.why_not == "Channel B doesn't take electronics and games."


def test_apparel_with_no_brand_can_go_on_channel_a_only() -> None:
    (a, b) = channel_options(apparel(product="canvas jacket"))
    assert a.takes
    assert not b.takes
    assert b.why_not == "Channel B needs a brand, and the item card has none."


@pytest.mark.parametrize(
    ("facts", "name"),
    [
        (JACKET, "Coats and jackets"),
        # The narrower season comes first in the calendar, so it wins over any sweater.
        (apparel(product="ugly sweater", visible_text="Merry Christmas"), "Holiday sweaters"),
        (apparel(product="wool sweater"), "Sweaters"),
        (apparel(product="Hiking Boots"), "Boots"),
        (apparel(product="flip-flops"), "Sandals"),
        (apparel(product="quarter zip", material="fleece"), "Sweaters"),
        (apparel(brand="Kansas City Chiefs", product="t-shirt"), "Football gear"),
    ],
)
def test_an_item_matches_the_first_season_with_a_word_on_its_card(
    facts: ListingFacts, name: str
) -> None:
    found = matching_season(facts, CALENDAR)
    assert found is not None
    assert found.name == name


@pytest.mark.parametrize(
    "facts",
    [
        apparel(brand="Levi's", product="501 jeans"),
        # A word only matches whole, so "coat" isn't found in "coated".
        apparel(product="coated denim skirt"),
        # Every season is apparel, so a football game is not football gear.
        GAME,
    ],
)
def test_an_item_with_no_season_word_matches_no_season(facts: ListingFacts) -> None:
    assert matching_season(facts, CALENDAR) is None
    advice = advise(facts, CALENDAR, TODAY)
    assert advice.timing.season is None
    assert advice.timing.release_month is None


@pytest.mark.parametrize(
    ("months", "today", "held_until"),
    [
        ([8, 9, 10, 11, 12, 1], date(2026, 11, 4), None),
        # A season that runs across the year end is in season in January too.
        ([8, 9, 10, 11, 12, 1], date(2027, 1, 31), None),
        ([8, 9, 10, 11, 12, 1], date(2027, 2, 1), date(2027, 8, 1)),
        ([3, 4, 5, 6, 7], date(2026, 11, 4), date(2027, 3, 1)),
        ([11, 12], date(2027, 1, 15), date(2027, 11, 1)),
        ([12, 1], date(2026, 10, 1), date(2026, 12, 1)),
        ([1], date(2026, 12, 31), date(2027, 1, 1)),
    ],
)
def test_an_item_out_of_season_is_held_until_its_next_month(
    months: list[int], today: date, held_until: date | None
) -> None:
    assert release_month(months, today) == held_until


@pytest.mark.parametrize(
    ("months", "words"),
    [
        ([8, 9, 10, 11, 12, 1], "August to January"),
        ([3, 4, 5, 6, 7], "March to July"),
        ([12, 1], "December to January"),
        ([1, 3, 5], "January, March and May"),
        ([4, 11, 12, 1], "April and November to January"),
        ([6], "June"),
    ],
)
def test_the_months_read_as_runs(months: list[int], words: str) -> None:
    assert month_span(months) == words


@pytest.mark.parametrize(
    ("facts", "today", "reason"),
    [
        (
            JACKET,
            TODAY,
            "Channel A and Channel B both take apparel, and its season, Coats and jackets, runs "
            "from August to January, so list it now.",
        ),
        (
            apparel(product="swimsuit"),
            TODAY,
            "Only Channel A takes it, because Channel B needs a brand and the card has none, and "
            "its season, Swimwear, runs from March to July, so hold it until March 2027.",
        ),
        (
            GAME,
            TODAY,
            "Only Channel A takes electronics and games, and it matches no season, so list it now.",
        ),
    ],
)
def test_the_fixed_reason_restates_what_code_decided(
    facts: ListingFacts, today: date, reason: str
) -> None:
    assert template_reason(advise(facts, CALENDAR, today), facts) == reason


def reply(reason: str) -> str:
    return json.dumps({"reason": reason})


def test_the_model_words_the_reason_from_the_facts() -> None:
    chat = StubChat(reply("This jacket suits both channels and is in season, so list it now."))
    advice = advise(JACKET, CALENDAR, TODAY)
    result = write_reason(advice, JACKET, [chat])
    assert result.text == "This jacket suits both channels and is in season, so list it now."
    assert result.source is DraftSource.MODEL
    assert result.fallback_reason is None
    prompt = str(chat.calls[0][0]["content"])
    assert prompt.startswith("You write the reason")
    assert "- Item: Carhartt canvas jacket" in prompt
    assert "- Season: Coats and jackets, listed from August to January" in prompt
    assert "- Timing: list now" in prompt
    assert f"- Recommendation: {template_reason(advice, JACKET)}" in prompt


@pytest.mark.parametrize(
    "written",
    [
        # March isn't in the facts, which say to list it now.
        "Hold it until March, when coats sell.",
        "Coats sell 40% faster in winter, so list it now.",
    ],
)
def test_a_reason_with_a_month_or_number_the_facts_lack_is_refused(written: str) -> None:
    result = write_reason(advise(JACKET, CALENDAR, TODAY), JACKET, [StubChat(reply(written))])
    assert result.source is DraftSource.TEMPLATE
    assert result.fallback_reason is FallbackReason.FLAGGED
    assert result.text == template_reason(advise(JACKET, CALENDAR, TODAY), JACKET)


def test_a_reason_may_name_the_month_and_year_it_is_held_until() -> None:
    facts = apparel(brand="Speedo", product="swimsuit")
    written = "Swimwear sells from March to July, so hold it until March 2027."
    result = write_reason(advise(facts, CALENDAR, TODAY), facts, [StubChat(reply(written))])
    assert result.source is DraftSource.MODEL
    assert result.text == written


def test_a_reason_over_one_line_is_retried() -> None:
    chat = StubChat(reply("List it now.\nBoth channels take it."), reply("List it now."))
    result = write_reason(advise(JACKET, CALENDAR, TODAY), JACKET, [chat])
    assert result.text == "List it now."
    assert len(chat.calls) == 2


def test_a_failed_model_leaves_the_fixed_reason() -> None:
    result = write_reason(advise(JACKET, CALENDAR, TODAY), JACKET, [StubChat(500)])
    assert result.source is DraftSource.TEMPLATE
    assert result.fallback_reason is FallbackReason.MODEL_FAILED


def test_no_model_leaves_the_fixed_reason() -> None:
    result = write_reason(advise(JACKET, CALENDAR, TODAY), JACKET, [])
    assert result.source is DraftSource.TEMPLATE
    assert result.fallback_reason is FallbackReason.NOT_CONFIGURED


class SlowChat(StubChat):
    """Answers only once the test lets it, long after the screen has stopped waiting."""

    def __init__(self) -> None:
        super().__init__(reply("Too late."), name="slow")
        self.release = threading.Event()

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        self.release.wait(5)
        return super().complete(messages, json_mode=json_mode)


def test_a_slow_model_leaves_the_fixed_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(channel_timing, "REASON_SECONDS", 0.05)
    slow = SlowChat()
    try:
        result = write_reason(advise(JACKET, CALENDAR, TODAY), JACKET, [slow])
    finally:
        slow.release.set()
    assert result.source is DraftSource.TEMPLATE
    assert result.fallback_reason is FallbackReason.MODEL_FAILED


# Through the API, on real Postgres.


def recommendation(staff: TestClient, item_id: str) -> dict[str, Any]:
    response = staff.get(f"/items/{item_id}/channels")
    assert response.status_code == 200, response.text
    return response.json()


def save_calendar(managing: TestClient, *seasons: dict[str, Any]) -> None:
    current = managing.get("/settings").json()["seasonal_calendar"]["updated_at"]
    response = managing.put(
        "/settings/seasonal-calendar",
        json={"value": {"seasons": list(seasons)}, "expected_updated_at": current},
    )
    assert response.status_code == 200, response.text


def test_staff_see_the_channels_the_timing_and_the_reason(client: TestClient) -> None:  # noqa: F811
    page = recommendation(client, listed_item(client))
    assert page == {
        "channels": [
            {"channel": "channel_a", "takes": True, "why_not": None},
            {"channel": "channel_b", "takes": True, "why_not": None},
        ],
        "timing": {
            "season": "Coats and jackets",
            "season_months": [1, 8, 9, 10, 11, 12],
            "season_span": "August to January",
            "release_month": None,
        },
        "reason": REASON,
        "reason_source": "model",
        "reason_fallback": None,
    }


def test_a_game_is_recommended_for_channel_a_only(client: TestClient) -> None:  # noqa: F811
    model_replies(category="electronics_games", brand="Nintendo", product="Switch Lite console")
    page = recommendation(client, listed_item(client))
    assert [(option["channel"], option["takes"]) for option in page["channels"]] == [
        ("channel_a", True),
        ("channel_b", False),
    ]
    assert page["channels"][1]["why_not"] == "Channel B doesn't take electronics and games."
    assert page["timing"]["season"] is None


def test_a_calendar_changed_on_the_settings_page_changes_the_hint(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
) -> None:
    item_id = listed_item(client)
    assert recommendation(client, item_id)["timing"]["release_month"] is None

    save_calendar(manager, season(months=[3, 4]))
    timing = recommendation(client, item_id)["timing"]
    assert timing == {
        "season": "Coats",
        "season_months": [3, 4],
        "season_span": "March to April",
        "release_month": "2027-03-01",
    }

    save_calendar(manager, season(match_words=["parka"]))
    assert recommendation(client, item_id)["timing"]["season"] is None


@pytest.mark.parametrize(
    ("providers", "fallback"),
    [([StubChat(500)], "model_failed"), ([], "not_configured")],
)
def test_the_recommendation_shows_with_the_fixed_reason_when_the_model_fails_or_is_missing(
    client: TestClient,  # noqa: F811
    providers: list[StubChat],
    fallback: str,
) -> None:
    item_id = listed_item(client)
    app.dependency_overrides[get_reason_providers] = lambda: providers
    page = recommendation(client, item_id)
    assert page["reason"] == (
        "Channel A and Channel B both take apparel, and its season, Coats and jackets, runs from "
        "August to January, so list it now."
    )
    assert page["reason_source"] == "template"
    assert page["reason_fallback"] == fallback
    assert [option["takes"] for option in page["channels"]] == [True, True]


def test_the_recommendation_shows_when_the_model_is_slow(
    client: TestClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id = listed_item(client)
    monkeypatch.setattr(channel_timing, "REASON_SECONDS", 0.05)
    slow = SlowChat()
    app.dependency_overrides[get_reason_providers] = lambda: [slow]
    try:
        page = recommendation(client, item_id)
    finally:
        slow.release.set()
    assert page["reason_source"] == "template"
    assert page["reason_fallback"] == "model_failed"
    assert page["timing"]["season"] == "Coats and jackets"


def test_staff_choose_which_channels_to_draft(client: TestClient) -> None:  # noqa: F811
    drafter = use_drafter(
        json.dumps(
            {"title": "Carhartt canvas jacket", "description": "A jacket.", "category": "Unisex"}
        )
    )
    item_id = listed_item(client)
    drafts = write_drafts(client, item_id, ["channel_b"])
    assert [draft["channel"] for draft in drafts] == ["channel_b"]
    assert len(drafter.calls) == 1
    # The choice is made once, so asking again with other channels returns the same drafts.
    assert write_drafts(client, item_id, ["channel_a", "channel_b"]) == drafts


def test_staff_cannot_choose_a_channel_that_does_not_take_the_category(client: TestClient) -> None:  # noqa: F811
    model_replies(category="electronics_games", brand="Nintendo", product="Switch console")
    item_id = listed_item(client)
    response = client.post(
        f"/items/{item_id}/drafts", json={"channels": ["channel_a", "channel_b"]}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Channel B doesn't take electronics and games."
    assert client.get(f"/items/{item_id}/drafts").json() == []


def test_staff_cannot_choose_channel_b_for_a_card_with_no_brand(
    client: TestClient,  # noqa: F811
    session: Session,
) -> None:
    item_id = listed_item(client)
    card = session.get_one(ItemCard, UUID(item_id))
    card.brand = None
    session.add(card)
    session.commit()
    channels = recommendation(client, item_id)["channels"]
    assert [option["takes"] for option in channels] == [True, False]

    response = client.post(f"/items/{item_id}/drafts", json={"channels": ["channel_b"]})
    assert response.status_code == 422
    assert response.json()["detail"] == "Channel B needs a brand, and the item card has none."
    assert [draft["channel"] for draft in write_drafts(client, item_id)] == ["channel_a"]


@pytest.mark.parametrize("body", [{}, {"channels": []}, {"channels": ["channel_c"]}])
def test_drafting_needs_a_channel_choice(client: TestClient, body: dict[str, Any]) -> None:  # noqa: F811
    item_id = listed_item(client)
    assert client.post(f"/items/{item_id}/drafts", json=body).status_code == 422


def item_row(session: Session, item_id: str) -> Item:
    row = session.get(Item, UUID(item_id), populate_existing=True)
    assert row is not None
    return row


def test_an_item_listed_now_gets_no_release_month(client: TestClient, session: Session) -> None:  # noqa: F811
    item_id = listed_item(client)
    write_drafts(client, item_id)
    assert item_row(session, item_id).release_month is None


def test_a_hold_sets_the_release_month_and_approval_holds_the_item(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    # Today as the approval step sees it, with the season starting next month.
    today = datetime.now(UTC).date()
    app.dependency_overrides[get_today] = lambda: today
    next_month = today.month % 12 + 1
    save_calendar(manager, season(months=[next_month]))
    use_reasoner(reply("Hold it for its season."))
    item_id = listed_item(client)
    held_until = date(today.year + 1 if next_month == 1 else today.year, next_month, 1)
    assert recommendation(client, item_id)["timing"]["release_month"] == held_until.isoformat()

    write_drafts(client, item_id)
    assert item_row(session, item_id).release_month == held_until
    assert client.post(f"/items/{item_id}/drafts/submit").status_code == 200
    assert manager.put(f"/items/{item_id}/storage", json=PACKAGE).status_code == 200
    page = approve(manager, item_id).json()
    assert page["status"] == "held_for_season"
    assert page["release_month"] == held_until.isoformat()
