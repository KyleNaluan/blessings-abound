from dataclasses import asdict, replace
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import (
    Category,
    Channel,
    Condition,
    Recommendation,
    StoreDepartment,
    SyntheticItem,
    SyntheticListing,
    TriageOutcome,
)
from app.settings import SyntheticSales
from app.synthetic_calibration import (
    REPORT_FILE,
    RESULTS_FILE,
    TARGETS,
    Target,
    render_report,
    results_json,
    run,
    score,
    shape_passes,
    sold_within,
    within_tolerance,
)
from app.synthetic_sales import History, Item, Listing, baseline, generate, load, price_band

PARAMS = SyntheticSales()
DAY = date(2026, 1, 5)


def item(number: int = 1, **changes: object) -> Item:
    values: dict[str, object] = {
        "id": number,
        "forwarded_on": DAY,
        "store_department": StoreDepartment.CLOTHING,
        "category": Category.APPAREL,
        "department": None,
        "condition": Condition.PRE_OWNED,
        "typical_price_cents": 4000,
        "recommendation": Recommendation.YES,
        "outcome": TriageOutcome.ACCEPTED,
        "overridden": False,
    }
    return Item(**{**values, **changes})  # pyright: ignore[reportArgumentType]


def listing(number: int, days_to_sell: int | None, channel: Channel = Channel.CHANNEL_A) -> Listing:
    sold_on = None if days_to_sell is None else DAY + timedelta(days=days_to_sell)
    return Listing(
        id=number,
        item_id=number,
        channel=channel,
        price_cents=4000,
        listed_on=DAY,
        sold_on=sold_on,
        ended_on=DAY + timedelta(days=90) if sold_on is None else None,
    )


def history(*days: int | None) -> History:
    return History(
        seed=0,
        items=[item(number) for number in range(1, len(days) + 1)],
        listings=[listing(number, day) for number, day in enumerate(days, start=1)],
    )


def test_the_same_seed_gives_the_same_history() -> None:
    assert generate(PARAMS, 44) == generate(PARAMS, 44)


def test_a_different_seed_gives_a_different_history() -> None:
    assert generate(PARAMS, 44) != generate(PARAMS, 45)


def test_the_configured_seed_is_used_unless_another_is_given() -> None:
    assert generate(PARAMS) == generate(PARAMS, PARAMS.seed)


def test_about_600_items_come_in_over_12_months() -> None:
    history = generate(PARAMS)
    assert 500 <= len(history.items) <= 700
    first, last = history.items[0].forwarded_on, history.items[-1].forwarded_on
    assert first >= PARAMS.first_day
    assert last < date(PARAMS.first_day.year + 1, PARAMS.first_day.month, 1)


def test_the_history_keeps_to_the_apps_own_rules() -> None:
    history = generate(PARAMS)
    by_id = {item.id: item for item in history.items}
    for row in history.items:
        assert (row.department is not None) == (row.category is Category.APPAREL)
        assert (row.store_department is StoreDepartment.CLOTHING) == (
            row.category is Category.APPAREL
        )
    assert {listing.item_id for listing in history.listings} == {
        row.id for row in history.items if row.outcome is TriageOutcome.ACCEPTED
    }
    for row in history.listings:
        if row.channel is Channel.CHANNEL_B:
            assert by_id[row.item_id].category is Category.APPAREL
        if row.sold_on is None:
            assert row.ended_on == row.listed_on + timedelta(days=PARAMS.max_days)
        else:
            assert 0 <= (row.sold_on - row.listed_on).days < PARAMS.max_days


def test_an_override_is_a_call_against_a_yes_or_a_no() -> None:
    for row in generate(PARAMS).items:
        against = (row.recommendation, row.outcome) in {
            (Recommendation.YES, TriageOutcome.REJECTED),
            (Recommendation.NO, TriageOutcome.ACCEPTED),
        }
        assert row.overridden == against


def test_the_baseline_adds_up_to_the_weibull_curve() -> None:
    for channel, scale, shape in (
        (Channel.CHANNEL_A, PARAMS.channel_a_scale_days, PARAMS.channel_a_shape),
        (Channel.CHANNEL_B, PARAMS.channel_b_scale_days, PARAMS.channel_b_shape),
    ):
        rates = baseline(PARAMS, channel)
        assert len(rates) == PARAMS.max_days
        assert sum(rates[:30]) == pytest.approx((30 / scale) ** shape)


@pytest.mark.parametrize(
    ("cents", "band"), [(1499, 0), (1500, 1), (2999, 1), (3000, 2), (24999, 4), (25000, 5)]
)
def test_price_bands_start_at_their_edges(cents: int, band: int) -> None:
    assert price_band(PARAMS, cents) == band


def test_every_parameter_says_where_it_comes_from() -> None:
    for name, field in SyntheticSales.model_fields.items():
        assert field.description, name
        assert field.description.startswith(("Assumed", "Calibrated", "Choice")), name


def test_the_seasonal_index_and_funnel_rates_are_labeled_assumed() -> None:
    fields = SyntheticSales.model_fields
    for name, field in fields.items():
        if "seasonal_index" in name or "accept_if" in name or name.endswith("_share"):
            assert (field.description or "").startswith("Assumed"), name


def _rows(session: Session) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    items = session.execute(select(SyntheticItem).order_by(SyntheticItem.id)).scalars()  # pyright: ignore[reportArgumentType]
    listings = session.execute(
        select(SyntheticListing).order_by(SyntheticListing.id)  # pyright: ignore[reportArgumentType]
    ).scalars()
    return (
        [row.model_dump() for row in items],
        [row.model_dump() for row in listings],
    )


def test_a_history_loads_into_a_fresh_database(session: Session) -> None:
    history = generate(PARAMS)
    load(session, history)
    items, listings = _rows(session)
    assert items == [asdict(row) for row in history.items]
    assert listings == [asdict(row) for row in history.listings]


def test_loading_again_replaces_the_history_with_identical_rows(session: Session) -> None:
    load(session, generate(PARAMS))
    first = _rows(session)
    load(session, generate(PARAMS, 7))
    assert _rows(session) != first
    load(session, generate(PARAMS))
    assert _rows(session) == first


def test_loading_leaves_the_real_sales_and_sync_log_alone(session: Session) -> None:
    load(session, generate(PARAMS))
    for table in ("items", "listings", "sale_events", "sync_log", "triage_log"):
        assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


def test_the_database_refuses_an_override_that_agrees(session: Session) -> None:
    wrong = replace(generate(PARAMS), listings=[])
    wrong.items[0] = replace(wrong.items[0], overridden=not wrong.items[0].overridden)
    with pytest.raises(IntegrityError, match="overridden_against_recommendation"):
        load(session, wrong)
        session.flush()


def test_the_database_refuses_a_listing_both_sold_and_ended(session: Session) -> None:
    good = generate(PARAMS)
    first = good.listings[0]
    both = replace(first, sold_on=first.listed_on, ended_on=first.listed_on + timedelta(days=90))
    with pytest.raises(IntegrityError, match="sold_or_ended"):
        load(session, replace(good, listings=[both]))
        session.flush()


def test_sold_within_counts_the_first_days_only() -> None:
    listings = history(0, 6, 7, 29, None).listings
    assert sold_within(listings, 7) == pytest.approx(2 / 5)
    assert sold_within(listings, 30) == pytest.approx(4 / 5)
    assert sold_within([], 30) is None


@pytest.mark.parametrize(
    ("mean", "passed"), [(6.0, True), (10.0, True), (5.99, False), (10.01, False)]
)
def test_a_target_passes_within_a_quarter_of_the_published_figure(
    mean: float, passed: bool
) -> None:
    assert within_tolerance(8.0, mean) is passed


def _share_sold_30() -> Target:
    return next(target for target in TARGETS if target.key == "a_sold_30")


def test_a_target_scores_the_mean_and_spread_over_the_histories() -> None:
    # 1 in 10 sold within 30 days in one history and 3 in 10 in the other, a mean of 20%.
    histories = [history(5, *[None] * 9), history(1, 2, 3, *[None] * 7)]
    result = score(_share_sold_30(), histories)
    assert result.mean == pytest.approx(0.2)
    assert (result.low, result.high) == (pytest.approx(0.11), pytest.approx(0.29))
    assert result.off_by == pytest.approx(0.2 / 0.122 - 1, abs=1e-4)
    assert result.passed is False
    assert result.seeds_measured == 2


def test_a_target_near_its_figure_passes() -> None:
    result = score(_share_sold_30(), [history(5, *[None] * 7)])
    assert result.mean == pytest.approx(0.125)
    assert result.passed is True


def test_a_history_with_nothing_to_measure_is_left_out() -> None:
    empty = History(seed=1, items=[], listings=[])
    result = score(_share_sold_30(), [empty, history(5, *[None] * 7)])
    assert result.seeds_measured == 1
    with pytest.raises(ValueError, match="a_sold_30"):
        score(_share_sold_30(), [empty])


@pytest.mark.parametrize(
    ("mean", "median", "skew", "p90", "passed"),
    [
        (29.0, 21.0, 0.67, 71.6, True),
        (40.0, 41.0, 0.1, 80.0, False),
        (30.0, 21.0, -0.1, 70.0, False),
        (30.0, 21.0, 0.5, 60.0, False),
    ],
)
def test_the_shape_check_needs_a_right_skew_and_a_long_tail(
    mean: float, median: float, skew: float, p90: float, passed: bool
) -> None:
    assert shape_passes(mean, median, skew, p90) is passed


def test_every_calibration_target_passes_with_the_configured_parameters() -> None:
    results = run()
    assert [result.key for result in results.targets if not result.passed] == []
    assert results.shape.passed


def test_the_saved_results_match_the_generator() -> None:
    results = run()
    hint = "Run `uv run python -m app.synthetic_calibration` in api/ to rewrite the saved results."
    assert results_json(results) == RESULTS_FILE.read_text(encoding="utf-8"), hint
    assert render_report(results) == REPORT_FILE.read_text(encoding="utf-8"), hint
