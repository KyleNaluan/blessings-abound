import pytest

from app.comp_filter import filter_comps
from app.comps import Comp
from app.models import Confidence, Recommendation
from app.pricing import PriceRange, price_range, worth_listing
from app.settings import PricingRules, Settings
from tests.serpapi_fixtures import ITEMS, load_comps

RULES = PricingRules()
NO_FACTOR = RULES.model_copy(update={"ask_to_sale_factor": 1.0})


def comps(*prices: int) -> list[Comp]:
    return [
        Comp(item_id=str(index), title="title", url="https://example.com", price_cents=price)
        for index, price in enumerate(prices)
    ]


def priced(typical_cents: int | None, confidence: Confidence = Confidence.HIGH) -> PriceRange:
    return PriceRange(
        low_cents=typical_cents,
        typical_cents=typical_cents,
        high_cents=typical_cents,
        comps_count=0 if typical_cents is None else 10,
        trimmed=[],
        confidence=confidence,
    )


def test_no_comps_gives_no_prices_and_low_confidence() -> None:
    result = price_range([], RULES)
    assert (result.low_cents, result.typical_cents, result.high_cents) == (None, None, None)
    assert result.comps_count == 0
    assert result.confidence is Confidence.LOW


def test_free_listing_is_not_priced() -> None:
    assert price_range(comps(0), RULES).comps_count == 0
    assert price_range(comps(0, 1000, 1100, 1200, 1300), NO_FACTOR).comps_count == 4


def test_one_comp_is_every_percentile_and_low_confidence() -> None:
    result = price_range(comps(4000), NO_FACTOR)
    assert (result.low_cents, result.typical_cents, result.high_cents) == (4000, 4000, 4000)
    assert result.confidence is Confidence.LOW


def test_few_comps_skip_the_trim() -> None:
    result = price_range(comps(1000, 1100, 90000), NO_FACTOR)
    assert result.trimmed == []
    assert result.comps_count == 3
    assert result.confidence is Confidence.LOW


def test_four_comps_are_enough_to_trim() -> None:
    result = price_range(comps(1000, 1100, 1200, 90000), NO_FACTOR)
    assert [comp.price_cents for comp in result.trimmed] == [90000]
    assert result.comps_count == 3


def test_percentiles_interpolate_and_then_scale_by_the_factor() -> None:
    prices = comps(1000, 2000, 3000, 4000, 5000)
    unscaled = price_range(prices, NO_FACTOR)
    assert (unscaled.low_cents, unscaled.typical_cents, unscaled.high_cents) == (2000, 3000, 4000)
    scaled = price_range(prices, RULES)
    assert (scaled.low_cents, scaled.typical_cents, scaled.high_cents) == (1290, 1935, 2580)


def test_percentiles_between_two_ranks() -> None:
    result = price_range(comps(1000, 2000, 3000, 4000), NO_FACTOR)
    assert (result.low_cents, result.typical_cents, result.high_cents) == (1750, 2500, 3250)


def test_trim_works_in_log_price_so_a_low_outlier_is_caught() -> None:
    result = price_range(comps(10, 2900, 3000, 3100, 3200, 3300), NO_FACTOR)
    assert [comp.price_cents for comp in result.trimmed] == [10]


def test_all_the_same_price_keeps_them_all() -> None:
    result = price_range(comps(*[2500] * 12), NO_FACTOR)
    assert result.trimmed == []
    assert result.comps_count == 12
    assert result.confidence is Confidence.HIGH


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        # Ten listings at a ratio of exactly 2 is the edge of high.
        ([1000, 1000, 1000, 1000, 1500, 1500, 2000, 2000, 2000, 2000], Confidence.HIGH),
        # Nine listings is too few for high, whatever the spread.
        ([1000] * 9, Confidence.MEDIUM),
        # Ten listings at a ratio past 2 falls to medium.
        ([1000, 1000, 1000, 1000, 1500, 1500, 2500, 2500, 2500, 2500], Confidence.MEDIUM),
        # Five listings at a ratio of exactly 3 is the edge of medium.
        ([1000, 1000, 2000, 3000, 3000], Confidence.MEDIUM),
        # Four listings is too few for medium.
        ([1000] * 4, Confidence.LOW),
        # Five listings past a ratio of 3 is low.
        ([1000, 1000, 2000, 4000, 4000], Confidence.LOW),
    ],
)
def test_confidence_rule(prices: list[int], expected: Confidence) -> None:
    assert price_range(comps(*prices), NO_FACTOR).confidence is expected


def test_many_comps_from_a_real_search() -> None:
    slug = "mario-kart-8-switch-game-conditions"
    kept = filter_comps(load_comps(slug), ITEMS[slug]).kept
    result = price_range(kept, RULES)
    assert result.comps_count + len(result.trimmed) == 59
    assert result.confidence is Confidence.HIGH
    assert result.typical_cents == round(3499 * RULES.ask_to_sale_factor)


def test_yes_at_exactly_the_threshold_with_the_net_beside_it() -> None:
    result = worth_listing(priced(3000), RULES)
    assert result.recommendation is Recommendation.YES
    # 3000 less 408 at 13.6%, 40 per order and 150 for supplies.
    assert result.net_after_fees_cents == 2402


def test_no_just_below_the_threshold() -> None:
    result = worth_listing(priced(2999), RULES)
    assert result.recommendation is Recommendation.NO
    assert result.net_after_fees_cents == 2401


def test_check_when_confidence_is_low_even_above_the_threshold() -> None:
    result = worth_listing(priced(9000, Confidence.LOW), RULES)
    assert result.recommendation is Recommendation.CHECK
    assert result.net_after_fees_cents == 7586


def test_check_with_no_net_when_there_are_no_comps() -> None:
    result = worth_listing(price_range([], RULES), RULES)
    assert result.recommendation is Recommendation.CHECK
    assert result.net_after_fees_cents is None


def test_net_can_go_below_zero() -> None:
    assert worth_listing(priced(100), RULES).net_after_fees_cents == -104


def test_rules_come_from_config() -> None:
    cheap = RULES.model_copy(update={"worth_listing_threshold_cents": 1000, "supplies_cents": 0})
    result = worth_listing(priced(1000), cheap)
    assert result.recommendation is Recommendation.YES
    assert result.net_after_fees_cents == 824


def test_every_rule_has_a_one_line_reason() -> None:
    for name, field in PricingRules.model_fields.items():
        assert field.description, name
        assert "\n" not in field.description, name


def test_factor_is_labeled_an_assumption() -> None:
    assert "Assumption" in (PricingRules.model_fields["ask_to_sale_factor"].description or "")


def test_rules_can_be_overridden_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICING", '{"worth_listing_threshold_cents": 2500}')
    rules = Settings().pricing
    assert rules.worth_listing_threshold_cents == 2500
    assert rules.ask_to_sale_factor == 0.645
