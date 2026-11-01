"""Price range, confidence and the worth-listing rule, as described in docs/architecture.md.

The functions here are pure: they take comps and rules and touch no database or network.
"""

import math

from pydantic import BaseModel

from app.comps import Comp
from app.models import Category, Confidence, Recommendation
from app.settings import PricingRules

LOW_PERCENTILE = 0.25
TYPICAL_PERCENTILE = 0.50
HIGH_PERCENTILE = 0.75


class PriceRange(BaseModel):
    """Expected sale prices, or no prices at all when nothing was left to price."""

    low_cents: int | None
    typical_cents: int | None
    high_cents: int | None
    comps_count: int
    trimmed: list[Comp]
    confidence: Confidence


class WorthListing(BaseModel):
    recommendation: Recommendation
    net_after_fees_cents: int | None


def ask_to_sale_factor(rules: PricingRules, category: Category) -> float:
    """The share of an asking price expected at sale, which differs by category."""
    if category is Category.ELECTRONICS_GAMES:
        return rules.games_ask_to_sale_factor
    return rules.ask_to_sale_factor


def _range_percentiles(rules: PricingRules, category: Category) -> tuple[float, float]:
    if category is Category.ELECTRONICS_GAMES:
        return rules.games_low_percentile, rules.games_high_percentile
    return LOW_PERCENTILE, HIGH_PERCENTILE


def price_range(comps: list[Comp], rules: PricingRules, category: Category) -> PriceRange:
    """Trim outliers, take the percentiles and scale asking prices to expected sale prices."""
    # A free listing says nothing about a sale price, and the trim takes the log of every price.
    priced = [comp for comp in comps if comp.price_cents > 0]
    kept, trimmed = _trim_outliers(priced, rules)
    if not kept:
        return PriceRange(
            low_cents=None,
            typical_cents=None,
            high_cents=None,
            comps_count=0,
            trimmed=trimmed,
            confidence=Confidence.LOW,
        )

    prices = sorted(comp.price_cents for comp in kept)
    low_fraction, high_fraction = _range_percentiles(rules, category)
    low = percentile(prices, low_fraction)
    typical = percentile(prices, TYPICAL_PERCENTILE)
    high = percentile(prices, high_fraction)
    factor = ask_to_sale_factor(rules, category)
    # Confidence reads the middle half in every category, so a wider range doesn't lower it.
    spread = percentile(prices, HIGH_PERCENTILE) / percentile(prices, LOW_PERCENTILE)
    return PriceRange(
        low_cents=round(low * factor),
        typical_cents=round(typical * factor),
        high_cents=round(high * factor),
        comps_count=len(kept),
        trimmed=trimmed,
        confidence=_confidence(len(kept), spread, rules),
    )


def worth_listing(price: PriceRange, rules: PricingRules) -> WorthListing:
    """Say yes, no or check from the typical sale price, with the net shown beside it."""
    typical = price.typical_cents
    if typical is None:
        return WorthListing(recommendation=Recommendation.CHECK, net_after_fees_cents=None)

    net = (
        typical - round(typical * rules.fee_rate) - rules.per_order_fee_cents - rules.supplies_cents
    )
    if price.confidence is Confidence.LOW:
        recommendation = Recommendation.CHECK
    elif typical >= rules.worth_listing_threshold_cents:
        recommendation = Recommendation.YES
    else:
        recommendation = Recommendation.NO
    return WorthListing(recommendation=recommendation, net_after_fees_cents=net)


def _trim_outliers(comps: list[Comp], rules: PricingRules) -> tuple[list[Comp], list[Comp]]:
    """Tukey fences on log price, skipped when too few comps remain to judge an outlier."""
    if len(comps) < rules.tukey_min_comps:
        return comps, []

    logs = sorted(math.log(comp.price_cents) for comp in comps)
    first = percentile(logs, LOW_PERCENTILE)
    third = percentile(logs, HIGH_PERCENTILE)
    margin = rules.tukey_fence_multiplier * (third - first)
    kept: list[Comp] = []
    trimmed: list[Comp] = []
    for comp in comps:
        inside = first - margin <= math.log(comp.price_cents) <= third + margin
        (kept if inside else trimmed).append(comp)
    return kept, trimmed


def percentile(ordered: list[float] | list[int], fraction: float) -> float:
    """Linear interpolation between the two closest ranks of an already sorted list."""
    position = (len(ordered) - 1) * fraction
    below = math.floor(position)
    above = math.ceil(position)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def _confidence(count: int, spread: float, rules: PricingRules) -> Confidence:
    if count >= rules.high_confidence_min_comps and spread <= rules.high_confidence_max_spread:
        return Confidence.HIGH
    if count >= rules.medium_confidence_min_comps and spread <= rules.medium_confidence_max_spread:
        return Confidence.MEDIUM
    return Confidence.LOW
