"""Price comps from SerpApi's eBay engine, with a 7 day cache in the comp_searches table.

A lookup searches active Buy It Now listings. When fewer than MIN_COMPS survive the relevance
filter, it drops the last word of the query and searches again, at most twice. Every response is
cached, and the searches spent in a calendar month are counted against a configurable budget.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx2
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import Category, CompSearch, Condition
from app.settings import Settings, get_settings

ENGINE = "ebay"
BUYING_FORMAT = "BIN"
CACHE_DAYS = 7
MIN_COMPS = 8
MAX_FALLBACKS = 2

# eBay uses different condition ids in the video games categories, see docs/serpapi-ebay-check.md.
USED_CONDITION_IDS = "3000"
VIDEO_GAME_CONDITION_IDS = "2750|4000|5000|6000"
NEW_WITH_TAGS_CONDITION_IDS = "1000"
NEW_WITHOUT_TAGS_CONDITION_IDS = "1500"
# eBay has no "new without tags" for games, and it labels this id "New (Other)" in their results.
VIDEO_GAME_NEW_OTHER_CONDITION_IDS = "2750"


def condition_ids(
    category: Category, video_game: bool = False, condition: Condition = Condition.PRE_OWNED
) -> str:
    """The LH_ItemCondition value for an item, so a search returns what the filter will accept."""
    is_game = category is Category.ELECTRONICS_GAMES and video_game
    if condition is Condition.NEW_WITH_TAGS:
        return NEW_WITH_TAGS_CONDITION_IDS
    if condition is Condition.NEW_WITHOUT_TAGS:
        return VIDEO_GAME_NEW_OTHER_CONDITION_IDS if is_game else NEW_WITHOUT_TAGS_CONDITION_IDS
    if is_game:
        return VIDEO_GAME_CONDITION_IDS
    return USED_CONDITION_IDS


class Comp(BaseModel):
    title: str
    price_cents: int
    condition: str | None = None
    url: str
    item_id: str


Filter = Callable[[list[Comp]], list[Comp]]


def keep_everything(comps: list[Comp]) -> list[Comp]:
    """The default relevance filter, replaced by the title filter once that exists."""
    return comps


class SearchBudgetSpentError(RuntimeError):
    pass


class SerpApiNotConfiguredError(RuntimeError):
    pass


class SerpApiError(RuntimeError):
    """A search that failed. The message never holds the request URL, which carries the key."""


class EbaySearch(Protocol):
    def __call__(self, query: str, condition: str) -> dict[str, Any]: ...


def serpapi_ebay_search(
    api_key: str, transport: httpx2.BaseTransport | None = None, timeout: float = 30.0
) -> EbaySearch:
    """A search function that calls SerpApi, one request per call."""

    def search(query: str, condition: str) -> dict[str, Any]:
        params = {
            "engine": ENGINE,
            "_nkw": query,
            "LH_ItemCondition": condition,
            "buying_format": BUYING_FORMAT,
            "ebay_domain": "ebay.com",
            "_ipg": "60",
            "api_key": api_key,
        }
        try:
            with httpx2.Client(transport=transport, timeout=timeout) as client:
                response = client.get(get_settings().serpapi_search_url, params=params)
            response.raise_for_status()
            body = response.json()
        except httpx2.HTTPStatusError as error:
            raise SerpApiError(f"SerpApi answered HTTP {error.response.status_code}") from None
        except (httpx2.HTTPError, ValueError) as error:
            raise SerpApiError(f"SerpApi could not be read: {type(error).__name__}") from None
        status = body.get("search_metadata", {}).get("status") if isinstance(body, dict) else None
        # Anything else would sit in the cache for 7 days and count as an answer.
        if status != "Success":
            raise SerpApiError(f"SerpApi reported the search status as {status}")
        return strip_private_fields(body)

    return search


def strip_private_fields(response: dict[str, Any]) -> dict[str, Any]:
    """Drops the key, in case SerpApi echoes it back, and seller usernames from anything saved."""
    parameters = response.get("search_parameters")
    if isinstance(parameters, dict):
        parameters.pop("api_key", None)
    for result in response.get("organic_results") or []:
        if isinstance(result, dict):
            result.pop("seller", None)
    return response


def parse_comps(response: dict[str, Any]) -> list[Comp]:
    """Maps organic results to comps, skipping rows without a single price or an item id."""
    comps = []
    for result in response.get("organic_results") or []:
        price = result.get("price")
        extracted = price.get("extracted") if isinstance(price, dict) else None
        item_id = result.get("product_id")
        if extracted is None or not item_id or not result.get("title") or not result.get("link"):
            continue
        comps.append(
            Comp(
                title=result["title"],
                price_cents=round(extracted * 100),
                condition=result.get("condition"),
                url=result["link"],
                item_id=str(item_id),
            )
        )
    return comps


@dataclass
class CompsLookup:
    comps: list[Comp]
    # The queries searched, in order, with the last one being the one whose comps are returned.
    queries: list[str]


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def searches_spent(session: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    statement = (
        select(func.count())
        .select_from(CompSearch)
        .where(col(CompSearch.fetched_at) >= _month_start(now))
    )
    return session.exec(statement).one()


def _fresh_response(
    session: Session, query: str, condition: str, now: datetime
) -> dict[str, Any] | None:
    statement = (
        select(CompSearch)
        .where(
            CompSearch.engine == ENGINE,
            CompSearch.query == query,
            CompSearch.condition == condition,
            CompSearch.buying_format == BUYING_FORMAT,
            col(CompSearch.fetched_at) >= now - timedelta(days=CACHE_DAYS),
        )
        .order_by(col(CompSearch.fetched_at).desc())
        .limit(1)
    )
    row = session.exec(statement).first()
    return row.response if row else None


def search_cached(
    session: Session,
    search: EbaySearch,
    query: str,
    condition: str,
    budget: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The cached response when it is under 7 days old, otherwise a new search that is saved."""
    now = now or datetime.now(UTC)
    cached = _fresh_response(session, query, condition, now)
    if cached is not None:
        return cached
    if searches_spent(session, now) >= budget:
        raise SearchBudgetSpentError(
            f"the monthly SerpApi budget of {budget} searches is spent, try again next month"
        )
    # A search can take 30 seconds, so don't hold a database transaction open across the call.
    session.commit()
    response = search(query, condition)
    session.add(
        CompSearch(
            engine=ENGINE,
            query=query,
            condition=condition,
            buying_format=BUYING_FORMAT,
            response=response,
            fetched_at=now,
        )
    )
    session.commit()
    return response


def fallback_queries(query: str) -> list[str]:
    """The query, then the query with its last word dropped, up to MAX_FALLBACKS times."""
    words = query.split()
    return [
        " ".join(words[: len(words) - dropped])
        for dropped in range(MAX_FALLBACKS + 1)
        if len(words) - dropped >= 1
    ]


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()


def find_comps(
    session: Session,
    query: str,
    condition: str,
    relevance_filter: Filter = keep_everything,
    search: EbaySearch | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> CompsLookup:
    """Looks up comps, dropping the last query word while fewer than MIN_COMPS survive the filter.

    Returns the comps of the first query that reaches MIN_COMPS, or of the last query searched.
    """
    settings = settings or get_settings()
    if search is None:
        if not settings.serpapi_api_key:
            raise SerpApiNotConfiguredError("set SERPAPI_API_KEY to look up comps")
        search = serpapi_ebay_search(settings.serpapi_api_key)
    query = normalize_query(query)
    queries: list[str] = []
    comps: list[Comp] = []
    for attempt in fallback_queries(query):
        response = search_cached(
            session, search, attempt, condition, settings.serpapi_monthly_budget, now
        )
        queries.append(attempt)
        comps = relevance_filter(parse_comps(response))
        if len(comps) >= MIN_COMPS:
            break
    return CompsLookup(comps=comps, queries=queries)
