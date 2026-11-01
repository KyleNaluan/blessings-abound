"""The photo-to-price steps behind the appraisal routes.

Everything here is a placeholder from the walking skeleton (#30). Each function is the seam its
issue replaces, so the routes and the web app stay as they are when the real step arrives.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models import Category, Confidence, Item, ItemCard, Recommendation


class ItemCardDraft(BaseModel):
    """What the vision model proposes for the card. Staff entries come in separately."""

    category: Category
    brand: str | None
    product: str | None
    visible_text: str | None
    search_query: str
    model_confidence: Confidence
    color: str | None
    material: str | None
    exact_model: str | None
    platform: str | None


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


def draft_item_card(item: Item) -> ItemCardDraft:
    # PLACEHOLDER: #10 replaces this with a vision model call on the item's photos.
    return ItemCardDraft(
        category=Category.APPAREL,
        brand="Placeholder Brand",
        product="Placeholder hooded sweatshirt",
        visible_text=None,
        search_query="placeholder brand hooded sweatshirt",
        model_confidence=Confidence.MEDIUM,
        color="Gray",
        material=None,
        exact_model=None,
        platform=None,
    )


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
