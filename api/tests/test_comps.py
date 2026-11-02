import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlmodel import Session

from app.comps import (
    CACHE_DAYS,
    USED_CONDITION_IDS,
    VIDEO_GAME_CONDITION_IDS,
    Comp,
    SearchBudgetSpentError,
    SerpApiError,
    SerpApiNotConfiguredError,
    condition_ids,
    fallback_queries,
    find_comps,
    parse_comps,
    search_cached,
    searches_spent,
    serpapi_ebay_search,
)
from app.models import Category, Condition
from app.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi"
SETTINGS = Settings(serpapi_api_key="test-key", serpapi_monthly_budget=10)
NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeSearch:
    """Answers from fixtures and counts the searches it was asked for."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, query: str, condition: str) -> dict[str, Any]:
        self.calls.append((query, condition))
        return self.responses.pop(0)


def test_parse_comps_maps_a_fixture_into_typed_comps() -> None:
    response = fixture("nike-air-max-90")
    comps = parse_comps(response)
    assert len(comps) == len(response["organic_results"])
    first = comps[0]
    assert first.price_cents == 2300
    assert first.item_id == "198752771377"
    assert first.condition == "Pre-Owned"
    assert first.url.startswith("https://www.ebay.com/itm/")
    assert first.title.startswith("Nike Air Max 90")


def test_parse_comps_skips_price_ranges() -> None:
    response = fixture("mario-kart-8-switch-game-conditions")
    ranges = [r for r in response["organic_results"] if "extracted" not in (r.get("price") or {})]
    assert ranges, "the fixture has a lot with a price range"
    assert len(parse_comps(response)) == len(response["organic_results"]) - len(ranges)


def test_condition_ids_per_category() -> None:
    assert condition_ids(Category.APPAREL) == USED_CONDITION_IDS == "3000"
    assert condition_ids(Category.ELECTRONICS_GAMES) == "3000"
    assert condition_ids(Category.ELECTRONICS_GAMES, video_game=True) == "2750|4000|5000|6000"
    assert VIDEO_GAME_CONDITION_IDS == "2750|4000|5000|6000"


@pytest.mark.parametrize(
    ("video_game", "condition", "ids"),
    [
        (False, Condition.NEW_WITH_TAGS, "1000"),
        (False, Condition.NEW_WITHOUT_TAGS, "1500"),
        (True, Condition.NEW_WITH_TAGS, "1000"),
        (True, Condition.NEW_WITHOUT_TAGS, "2750"),
    ],
)
def test_condition_ids_for_new_items(video_game: bool, condition: Condition, ids: str) -> None:
    assert condition_ids(Category.ELECTRONICS_GAMES, video_game, condition) == ids


def test_fallback_queries_drop_the_last_word_at_most_twice() -> None:
    assert fallback_queries("nike air max 90 sneakers") == [
        "nike air max 90 sneakers",
        "nike air max 90",
        "nike air max",
    ]
    assert fallback_queries("airpods pro") == ["airpods pro", "airpods"]
    assert fallback_queries("airpods") == ["airpods"]


def test_request_shape_and_key_stripping() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        body = fixture("airpods-pro")
        body["search_parameters"]["api_key"] = "test-key"
        return httpx2.Response(200, json=body)

    search = serpapi_ebay_search("test-key", httpx2.MockTransport(handler))
    response = search("airpods pro", "3000")

    (request,) = requests
    params = dict(request.url.params)
    assert request.url.host == "serpapi.com"
    assert params["engine"] == "ebay"
    assert params["_nkw"] == "airpods pro"
    assert params["LH_ItemCondition"] == "3000"
    assert params["buying_format"] == "BIN"
    assert params["api_key"] == "test-key"
    assert "api_key" not in response["search_parameters"]


def test_seller_names_are_not_kept() -> None:
    body = fixture("airpods-pro")
    body["organic_results"][0]["seller"] = {"username": "someone"}
    search = serpapi_ebay_search(
        "test-key", httpx2.MockTransport(lambda _: httpx2.Response(200, json=body))
    )
    assert all("seller" not in result for result in search("a", "3000")["organic_results"])


def raises_on(handler: Any) -> SerpApiError:
    search = serpapi_ebay_search("secret-test-key", httpx2.MockTransport(handler))
    with pytest.raises(SerpApiError) as caught:
        search("airpods pro", "3000")
    return caught.value


def test_a_failed_request_is_a_search_error_that_never_shows_the_key() -> None:
    error = raises_on(lambda _: httpx2.Response(429, json={"error": "out of searches"}))
    assert "429" in str(error)
    assert "secret-test-key" not in str(error)
    assert error.__cause__ is None


def test_a_connection_failure_is_a_search_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("timed out", request=request)

    error = raises_on(handler)
    assert "ConnectTimeout" in str(error)
    assert "secret-test-key" not in str(error)


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, text="not json"),
        httpx2.Response(200, json=["not", "an", "object"]),
        httpx2.Response(200, json={"search_metadata": {"status": "Error"}, "error": "nope"}),
    ],
    ids=["not json", "not an object", "error status"],
)
def test_a_reply_that_is_not_a_successful_search_is_an_error(response: httpx2.Response) -> None:
    raises_on(lambda _: response)


def test_a_failed_search_is_not_cached_or_counted(session: Session) -> None:
    def failing(query: str, condition: str) -> dict[str, Any]:
        raise SerpApiError("SerpApi answered HTTP 500")

    with pytest.raises(SerpApiError):
        search_cached(session, failing, "a", "3000", 2, NOW)
    assert searches_spent(session, NOW) == 0


def test_a_cached_response_is_reused_for_seven_days(session: Session) -> None:
    search = FakeSearch(fixture("airpods-pro"), fixture("airpods-pro"))
    first = search_cached(session, search, "airpods pro", "3000", 10, NOW)
    again = search_cached(session, search, "airpods pro", "3000", 10, NOW + timedelta(days=6))
    assert again == first
    assert len(search.calls) == 1

    search_cached(session, search, "airpods pro", "3000", 10, NOW + timedelta(days=CACHE_DAYS + 1))
    assert len(search.calls) == 2


def test_the_cache_is_keyed_by_query_and_condition(session: Session) -> None:
    search = FakeSearch(fixture("airpods-pro"), fixture("airpods-pro"), fixture("airpods-pro"))
    search_cached(session, search, "airpods pro", "3000", 10, NOW)
    search_cached(session, search, "airpods", "3000", 10, NOW)
    search_cached(session, search, "airpods pro", "2750|4000|5000|6000", 10, NOW)
    assert len(search.calls) == 3


def test_the_budget_refuses_cleanly_when_spent(session: Session) -> None:
    search = FakeSearch(*[fixture("airpods-pro") for _ in range(3)])
    search_cached(session, search, "a", "3000", 2, NOW)
    search_cached(session, search, "b", "3000", 2, NOW)
    assert searches_spent(session, NOW) == 2
    with pytest.raises(SearchBudgetSpentError, match="budget of 2"):
        search_cached(session, search, "c", "3000", 2, NOW)
    assert len(search.calls) == 2
    # A cached query still answers, and a new month starts a new count.
    search_cached(session, search, "a", "3000", 2, NOW)
    search_cached(session, search, "c", "3000", 2, NOW + timedelta(days=30))
    assert len(search.calls) == 3


def test_enough_comps_means_one_search(session: Session) -> None:
    search = FakeSearch(fixture("nike-air-max-90"))
    lookup = find_comps(
        session, "Nike Air Max 90 sneakers", "3000", search=search, settings=SETTINGS, now=NOW
    )
    assert lookup.queries == ["Nike Air Max 90 sneakers"]
    assert len(lookup.comps) >= 8


def test_too_few_comps_drops_the_last_word_twice_then_stops(session: Session) -> None:
    def keep_two(comps: list[Comp]) -> list[Comp]:
        return comps[:2]

    search = FakeSearch(*[fixture("nike-air-max-90") for _ in range(3)])
    lookup = find_comps(
        session, "nike air max 90 sneakers", "3000", keep_two, search, SETTINGS, NOW
    )
    assert lookup.queries == ["nike air max 90 sneakers", "nike air max 90", "nike air max"]
    assert [call[0] for call in search.calls] == lookup.queries
    assert len(lookup.comps) == 2


def test_the_fallback_stops_once_enough_comps_survive(session: Session) -> None:
    search = FakeSearch(fixture("nike-air-max-90"), fixture("nike-air-max-90"))
    calls = 0

    def second_query_is_enough(comps: list[Comp]) -> list[Comp]:
        nonlocal calls
        calls += 1
        return comps[:3] if calls == 1 else comps

    lookup = find_comps(
        session, "nike air max 90", "3000", second_query_is_enough, search, SETTINGS, NOW
    )
    assert lookup.queries == ["nike air max 90", "nike air max"]
    assert len(search.calls) == 2


def test_the_injected_filter_drops_comps(session: Session) -> None:
    search = FakeSearch(fixture("nintendo-switch-console"))

    def no_bundles(comps: list[Comp]) -> list[Comp]:
        return [c for c in comps if "bundle" not in c.title.lower()]

    lookup = find_comps(
        session, "nintendo switch console", "3000", no_bundles, search, SETTINGS, NOW
    )
    assert all("bundle" not in c.title.lower() for c in lookup.comps)


def test_find_comps_needs_a_key_when_no_search_is_given(session: Session) -> None:
    with pytest.raises(SerpApiNotConfiguredError):
        find_comps(session, "airpods pro", "3000", settings=Settings(serpapi_api_key=None))
