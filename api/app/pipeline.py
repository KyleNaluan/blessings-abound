"""The photo-to-price steps behind the appraisal routes.

Each function marked PLACEHOLDER is left from the walking skeleton (#30), and it is the seam its
issue replaces, so the routes and the web app stay as they are when the real step arrives.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.ai import ChatModel
from app.models import Confidence, ItemCard, Recommendation
from app.settings import get_settings
from app.storage import Storage
from app.vision import ItemCardDraft, prepare_photo, read_item_card


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
    return read_item_card(photos, providers, _staff_notes(staff_entries, notes)).card


def _staff_notes(staff_entries: dict[str, Any], notes: str | None) -> str | None:
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


def price_item(card: ItemCard) -> PriceResult:
    # PLACEHOLDER: #15 replaces the price range and #16 the recommendation, computed from comps.
    return PriceResult(
        price_low_cents=2500,
        price_typical_cents=3500,
        price_high_cents=4800,
        net_after_fees_cents=2834,
        comps_count=12,
        confidence=Confidence.HIGH,
        recommendation=Recommendation.YES,
        rules_config={"placeholder": True},
        explanation="Placeholder price. No comps were searched for this item.",
    )
