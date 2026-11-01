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
    PriceGuideReference,
    Results,
    SavedSearches,
    baseline_prices,
    evaluate,
    fresh_is_ready,
    load_fresh_items,
    load_items,
    render_report,
    results_json,
    score,
    slim_response,
    summarize,
)
from app.models import Category
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


def test_fresh_items_are_games_and_hardware_with_no_overlap_with_the_tuning_items() -> None:
    fresh = load_fresh_items()
    assert 13 <= len(fresh) <= 17
    tuning = load_items()
    assert not {item.id for item in fresh} & {item.id for item in tuning}
    tuning_links = {getattr(item.reference, "url", None) for item in tuning}
    tuning_photos = {item.photo.sha1 for item in tuning}
    for item in fresh:
        assert item.category is Category.ELECTRONICS_GAMES
        assert item.photo.license
        assert item.photo.author
        assert isinstance(item.reference, PriceGuideReference)
        assert item.reference.url not in tuning_links
        assert item.photo.sha1 not in tuning_photos


def test_the_saved_results_match_what_the_code_produces(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A PRICING override in a developer's .env must not fail this, so it uses the default rules.
    monkeypatch.setattr(get_settings(), "pricing", PricingRules())
    items = load_items()
    fresh = load_fresh_items()
    results = evaluate(items, fresh, session, SavedSearches())
    hint = "run `uv run python -m app.evaluate` in api/ and commit what changes"
    assert results_json(results) == RESULTS_FILE.read_text(), hint
    assert render_report(items, fresh, results) == REPORT_FILE.read_text(), hint


def _report_and_results(session: Session, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Results]:
    monkeypatch.setattr(get_settings(), "pricing", PricingRules())
    items = load_items()
    fresh = load_fresh_items()
    results = evaluate(items, fresh, session, SavedSearches())
    return render_report(items, fresh, results), results


def test_the_report_says_when_a_category_is_not_scored(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, _ = _report_and_results(session, monkeypatch)
    assert "**Not scored yet: apparel.**" in report
    assert "[PriceCharting](https://www.pricecharting.com/" in report


def test_the_first_eighteen_are_labeled_tuning_data_and_keep_their_baseline(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, results = _report_and_results(session, monkeypatch)
    tuning = results.groups["tuning"]
    assert tuning.pipeline.items == 18
    assert (tuning.baseline.in_range, tuning.baseline.median_error_percent) == (13, 15.1)
    assert "## Tuning data: the first 18 games and hardware items" in report
    assert "it isn't the result" in report


def test_the_like_for_like_row_is_the_same_comps_at_the_baselines_percentiles(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, results = _report_and_results(session, monkeypatch)
    for row in results.items:
        assert row.pipeline_middle_half.typical_cents == row.pipeline.typical_cents
        assert row.pipeline_middle_half.comps_count == row.pipeline.comps_count


def test_fresh_items_stay_unscored_until_every_card_is_read(tmp_path: Path) -> None:
    assert not fresh_is_ready([])
    assert load_fresh_items(tmp_path / "missing.json") == []
    item = EvalItem.model_validate(
        {
            "id": "not-a-saved-card",
            "name": "An item",
            "category": "electronics_games",
            "staff": {},
            "photo": PHOTO,
            "reference": {
                "kind": "price_guide",
                "source": "PriceCharting",
                "tier": "loose",
                "price_cents": 1000,
                "url": "https://example.com",
                "recorded_on": "2026-11-01",
                "sales_volume": "1 sale per day",
            },
        }
    )
    assert not fresh_is_ready([item])
