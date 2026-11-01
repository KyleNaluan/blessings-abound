import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlmodel import Session

from app.comps import Comp
from app.evaluate import (
    REPORT_FILE,
    RESULTS_FILE,
    EvalItem,
    EvaluationStopped,
    HandRecordedReference,
    SavedSearches,
    baseline_prices,
    evaluate,
    load_items,
    render_report,
    results_json,
    score,
    slim_response,
    summarize,
)
from app.settings import PricingRules, get_settings

PHOTO = {
    "file": "jacket.jpg",
    "url": "https://example.com/jacket.jpg",
    "page": "https://example.com/jacket",
    "sha1": "abc",
    "license": "CC0",
    "author": "A photographer",
}


def comp(price_cents: int) -> Comp:
    return Comp(title="item", price_cents=price_cents, url="https://example.com", item_id="1")


def test_a_reference_on_the_edge_of_the_range_is_in_range() -> None:
    prices = score(1000, 1000, 1500, 2000)
    assert prices.in_range
    assert prices.error_percent == 50.0


def test_no_price_is_out_of_range_with_no_error() -> None:
    prices = score(1000, None, None, None)
    assert not prices.in_range
    assert prices.error_percent is None


def test_the_baseline_uses_every_listing_with_no_factor() -> None:
    prices = baseline_prices([comp(100), comp(200), comp(300), comp(400), comp(50000)], 300)
    assert (prices.low_cents, prices.typical_cents, prices.high_cents) == (200, 300, 400)
    assert prices.comps_count == 5


def test_an_item_with_no_price_lowers_the_rate_but_not_the_median_error() -> None:
    summary = summarize([score(1000, 900, 1100, 1200), score(1000, None, None, None)])
    assert (summary.items, summary.priced, summary.in_range) == (2, 1, 1)
    assert summary.in_range_rate == 0.5
    assert summary.median_error_percent == 10.0


def test_a_hand_recorded_apparel_price_loads_with_no_code_change() -> None:
    item = EvalItem.model_validate(
        {
            "id": "jacket",
            "name": "A jacket",
            "category": "apparel",
            "staff": {"department": "mens", "size": "L"},
            "photo": PHOTO,
            "reference": {
                "kind": "hand_recorded",
                "source": "eBay sold filter",
                "price_cents": 4500,
                "search_url": "https://example.com/search",
                "recorded_on": "2026-11-02",
                "recorded_by": "A teammate",
            },
        }
    )
    assert isinstance(item.reference, HandRecordedReference)


def test_a_hand_recorded_price_needs_its_link_date_and_recorder() -> None:
    with pytest.raises(ValidationError):
        HandRecordedReference.model_validate(
            {"kind": "hand_recorded", "source": "eBay sold filter", "price_cents": 4500}
        )


def test_saved_responses_hold_no_key_sellers_or_archive_links() -> None:
    slim = slim_response(
        {
            "search_metadata": {"raw_html_file": "https://serpapi.com/archive"},
            "search_parameters": {"_nkw": "jacket", "api_key": "secret"},
            "search_information": {"total_results": 5},
            "organic_results": [
                {"title": "A", "price": {"extracted": 5.0}, "seller": {"username": "someone"}}
            ],
        }
    )
    text = json.dumps(slim)
    assert "secret" not in text
    assert "someone" not in text
    assert "archive" not in text
    assert slim["total_results"] == 5


class CountingSearch:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, query: str, condition: str) -> dict[str, Any]:
        self.calls += 1
        return {"search_parameters": {"_nkw": query}, "organic_results": []}


def test_a_saved_search_is_never_repeated(tmp_path: Path) -> None:
    live = CountingSearch()
    searches = SavedSearches(tmp_path, live, allowed=1)
    searches("jacket", "3000")
    searches("jacket", "3000")
    assert live.calls == 1
    assert searches.spent == 1


def test_a_replay_refuses_to_search(tmp_path: Path) -> None:
    with pytest.raises(EvaluationStopped, match="--live-searches"):
        SavedSearches(tmp_path)("jacket", "3000")


def test_the_run_stops_at_its_allowance(tmp_path: Path) -> None:
    live = CountingSearch()
    searches = SavedSearches(tmp_path, live, allowed=1)
    searches("jacket", "3000")
    with pytest.raises(EvaluationStopped, match="used up"):
        searches("coat", "3000")
    assert live.calls == 1


def test_the_run_stops_at_the_set_budget(tmp_path: Path) -> None:
    live = CountingSearch()
    SavedSearches(tmp_path, live, allowed=1, budget=1)("jacket", "3000")
    with pytest.raises(EvaluationStopped, match="budget"):
        SavedSearches(tmp_path, live, allowed=1, budget=1)("coat", "3000")
    assert live.calls == 1


def test_every_item_records_its_photo_license_and_price_source() -> None:
    items = load_items()
    assert len({item.id for item in items}) == len(items)
    for item in items:
        assert item.photo.license
        assert item.photo.author
        assert item.reference.price_cents > 0


def test_the_saved_results_match_what_the_code_produces(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A PRICING override in a developer's .env must not fail this, so it uses the default rules.
    monkeypatch.setattr(get_settings(), "pricing", PricingRules())
    items = load_items()
    results = evaluate(items, session, SavedSearches())
    hint = "run `uv run python -m app.evaluate` in api/ and commit what changes"
    assert results_json(results) == RESULTS_FILE.read_text(), hint
    assert render_report(items, results) == REPORT_FILE.read_text(), hint


def test_the_report_says_when_a_category_is_not_scored(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "pricing", PricingRules())
    items = load_items()
    report = render_report(items, evaluate(items, session, SavedSearches()))
    assert "**Not scored yet: apparel.**" in report
    assert "[PriceCharting](https://www.pricecharting.com/" in report
