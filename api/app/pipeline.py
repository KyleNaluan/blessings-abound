"""The photo-to-price steps behind the appraisal routes.

Each function marked PLACEHOLDER is left from the walking skeleton (#30), and it is the seam its
issue replaces, so the routes and the web app stay as they are when the real step arrives.
"""

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Session

from app.ai import ChatModel
from app.comp_filter import ItemFacts, filter_comps, is_hardware
from app.comps import (
    EbaySearch,
    SearchBudgetSpentError,
    SerpApiError,
    SerpApiNotConfiguredError,
    condition_ids,
    find_comps,
)
from app.models import Category, Confidence, ItemCard, Recommendation
from app.pricing import PriceRange, WorthListing, price_range, worth_listing
from app.settings import PricingRules, get_settings
from app.storage import Storage
from app.vision import ItemCardDraft, prepare_photo, read_item_card

logger = logging.getLogger(__name__)


class PriceResult(BaseModel):
    price_low_cents: int | None
    price_typical_cents: int | None
    price_high_cents: int | None
    net_after_fees_cents: int | None
    comps_count: int
    confidence: Confidence
    recommendation: Recommendation
    rules_config: dict[str, Any]
    explanation: str | None


def placeholder_sku(item_id: UUID) -> str:
    # PLACEHOLDER: #37 replaces this with the lister's initials, the date and a daily sequence.
    return f"PLACEHOLDER-{item_id.hex[:12]}"


def placeholder_photo_hash(item_id: UUID) -> str:
    # PLACEHOLDER: #9 replaces this with the real hash. It is unique per item until then, so the
    # duplicate guard in #37 can't match two placeholder rows against each other.
    return f"placeholder-{item_id.hex}"


def draft_item_card(
    photo_keys: list[str],
    staff_entries: dict[str, Any],
    notes: str | None,
    storage: Storage,
    providers: list[ChatModel],
) -> ItemCardDraft:
    """Ask the vision model for its part of the card, telling it what staff already entered."""
    photos = [prepare_photo(storage.read(key)) for key in photo_keys]
    return read_item_card(photos, providers, staff_notes(staff_entries, notes)).card


def staff_notes(staff_entries: dict[str, Any], notes: str | None) -> str | None:
    lines = [f"{name}: {value}" for name, value in staff_entries.items() if value not in (None, [])]
    if notes:
        lines.append(notes)
    return "; ".join(lines) or None


def needs_confirmation(brand: str | None, model_confidence: Confidence) -> bool:
    """Whether staff must confirm the card before any search."""
    # A missing brand counts too, because the search would have nothing specific to look for.
    order = list(Confidence)
    bar = get_settings().item_card_min_confidence
    return brand is None or order.index(model_confidence) < order.index(bar)


def item_facts(card: ItemCard) -> ItemFacts:
    """What the comp filter compares each listing with."""
    # The filter reads tall, plus and petite from the size, which the card keeps apart.
    size = " ".join(part for part in (card.size_type, card.size) if part) or None
    return ItemFacts(
        category=card.category,
        product=card.product,
        exact_model=card.exact_model,
        platform=card.platform,
        condition=card.condition,
        department=card.department,
        size=size,
        complete_in_box=card.complete_in_box,
    )


def _search_condition(facts: ItemFacts) -> str:
    video_game = (
        facts.category is Category.ELECTRONICS_GAMES
        and facts.platform is not None
        and not is_hardware(facts)
    )
    return condition_ids(facts.category, video_game, facts.condition)


def price_item(card: ItemCard, session: Session, search: EbaySearch | None) -> PriceResult:
    """Price the item from comps, or say plainly why there is no price."""
    rules = get_settings().pricing
    facts = item_facts(card)
    query = card.search_query
    condition = _search_condition(facts)

    def no_price(outcome: str, explanation: str) -> PriceResult:
        return _no_price(rules, _search_record(outcome, query, condition, [query]), explanation)

    try:
        lookup = find_comps(
            session, query, condition, lambda comps: filter_comps(comps, facts).kept, search
        )
    except SearchBudgetSpentError as error:
        logger.warning("%s", error)
        return no_price(
            "budget_spent",
            "This month's eBay search budget is spent, so no comps were searched and this item has "
            "no price. Check it by hand, or appraise it again next month.",
        )
    except SerpApiNotConfiguredError as error:
        logger.warning("%s", error)
        return no_price(
            "not_configured",
            "The eBay search isn't set up on this server, so no comps were searched and this item "
            "has no price. Check it by hand.",
        )
    except SerpApiError as error:
        logger.warning("%s", error)
        return no_price(
            "search_failed",
            "The eBay search failed just now, so this item has no price. Appraise it again in a "
            "moment, or check it by hand.",
        )

    price = price_range(lookup.comps, rules, card.category)
    worth = worth_listing(price, rules)
    if price.typical_cents is None:
        searched = '", "'.join(lookup.queries)
        return _no_price(
            rules,
            _search_record("no_comps", query, condition, lookup.queries),
            f'No usable comps came back from eBay for "{searched}", so this item has no price. '
            "Check it by hand, or edit the search on the card and appraise it again.",
        )
    return PriceResult(
        price_low_cents=price.low_cents,
        price_typical_cents=price.typical_cents,
        price_high_cents=price.high_cents,
        net_after_fees_cents=worth.net_after_fees_cents,
        comps_count=price.comps_count,
        confidence=price.confidence,
        recommendation=worth.recommendation,
        rules_config=_rules_config(
            rules, _search_record("priced", query, condition, lookup.queries)
        ),
        explanation=_explain(price, worth, rules),
    )


def _no_price(rules: PricingRules, search: dict[str, Any], explanation: str) -> PriceResult:
    return PriceResult(
        price_low_cents=None,
        price_typical_cents=None,
        price_high_cents=None,
        net_after_fees_cents=None,
        comps_count=0,
        confidence=Confidence.LOW,
        recommendation=Recommendation.CHECK,
        rules_config=_rules_config(rules, search),
        explanation=explanation,
    )


def _search_record(outcome: str, query: str, condition: str, queries: list[str]) -> dict[str, Any]:
    return {"outcome": outcome, "query": query, "condition": condition, "queries": queries}


def _rules_config(rules: PricingRules, search: dict[str, Any]) -> dict[str, Any]:
    return {"pricing": rules.model_dump(), "search": search}


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _explain(price: PriceRange, worth: WorthListing, rules: PricingRules) -> str:
    """The template explanation, every number in it computed from comps."""
    # Only called with a typical price, which also means a net and the rest of the range.
    assert price.typical_cents is not None and price.low_cents is not None
    assert price.high_cents is not None and worth.net_after_fees_cents is not None
    count = f"{price.comps_count} similar eBay listing{'' if price.comps_count == 1 else 's'}"
    bar = _money(rules.worth_listing_threshold_cents)
    typical = _money(price.typical_cents)
    if worth.recommendation is Recommendation.CHECK:
        verdict = f"Confidence is {price.confidence.value}, so check this one by hand."
    elif worth.recommendation is Recommendation.YES:
        verdict = f"That meets the {bar} bar, so it's worth listing."
    else:
        verdict = f"That's under the {bar} bar, so it isn't worth listing."
    return (
        f"The expected sale price is {typical}, in a range of {_money(price.low_cents)} to "
        f"{_money(price.high_cents)}, from the asking prices of {count}. "
        f"That leaves {_money(worth.net_after_fees_cents)} after fees and supplies. {verdict}"
    )
