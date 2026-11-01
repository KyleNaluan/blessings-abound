"""Price range, confidence and the worth-listing rule, as described in docs/architecture.md.

The functions here are pure: they take comps and rules and touch no database or network.
"""

import math

from pydantic import BaseModel, ConfigDict, Field

from app.models import Confidence, Recommendation
from app.settings import PricingRules

LOW_PERCENTILE = 0.25
TYPICAL_PERCENTILE = 0.50
HIGH_PERCENTILE = 0.75


class Comp(BaseModel):
    """One active eBay listing, with an asking price in cents."""

    model_config = ConfigDict(frozen=True)

    item_id: str
    title: str
    url: str
    condition: str | None = None
    # None when the listing shows a from-to range across variants instead of one price.
    price_cents: int | None = Field(default=None, gt=0)


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


def price_range(comps: list[Comp], rules: PricingRules) -> PriceRange:
    """Trim outliers, take the percentiles and scale asking prices to expected sale prices."""
    priced = [comp for comp in comps if comp.price_cents is not None]
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

    prices = sorted(_price(comp) for comp in kept)
    low = _percentile(prices, LOW_PERCENTILE)
    typical = _percentile(prices, TYPICAL_PERCENTILE)
    high = _percentile(prices, HIGH_PERCENTILE)
    factor = rules.ask_to_sale_factor
    return PriceRange(
        low_cents=round(low * factor),
        typical_cents=round(typical * factor),
        high_cents=round(high * factor),
        comps_count=len(kept),
        trimmed=trimmed,
        confidence=_confidence(len(kept), high / low, rules),
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


def _price(comp: Comp) -> int:
    if comp.price_cents is None:
        raise ValueError(f"Comp {comp.item_id} has no single price")
    return comp.price_cents


def _trim_outliers(comps: list[Comp], rules: PricingRules) -> tuple[list[Comp], list[Comp]]:
    """Tukey fences on log price, skipped when too few comps remain to judge an outlier."""
    if len(comps) < rules.tukey_min_comps:
        return comps, []

    logs = sorted(math.log(_price(comp)) for comp in comps)
    first = _percentile(logs, LOW_PERCENTILE)
    third = _percentile(logs, HIGH_PERCENTILE)
    margin = rules.tukey_fence_multiplier * (third - first)
    kept: list[Comp] = []
    trimmed: list[Comp] = []
    for comp in comps:
        inside = first - margin <= math.log(_price(comp)) <= third + margin
        (kept if inside else trimmed).append(comp)
    return kept, trimmed


def _percentile(ordered: list[float] | list[int], fraction: float) -> float:
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
