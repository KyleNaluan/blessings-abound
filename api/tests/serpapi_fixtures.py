"""Reads the committed SerpApi responses into comps, and the item each search stands for."""

import json
from pathlib import Path
from typing import Any

from app.comp_filter import ItemFacts
from app.models import Category, Department
from app.pricing import Comp

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi"

ITEMS = {
    "levis-501-jeans": ItemFacts(
        category=Category.APPAREL, product="Levi's 501 jeans", department=Department.MENS
    ),
    "nike-air-max-90": ItemFacts(
        category=Category.APPAREL, product="Nike Air Max 90", department=Department.MENS
    ),
    "patagonia-better-sweater": ItemFacts(
        category=Category.APPAREL, product="Better Sweater fleece", department=Department.MENS
    ),
    "carhartt-detroit-jacket": ItemFacts(
        category=Category.APPAREL,
        product="Detroit jacket",
        department=Department.MENS,
        size="L",
    ),
    "lululemon-align-leggings": ItemFacts(
        category=Category.APPAREL, product="Align leggings", department=Department.WOMENS
    ),
    "airpods-pro": ItemFacts(category=Category.ELECTRONICS_GAMES, product="Apple AirPods Pro"),
    "mario-kart-8-switch": ItemFacts(
        category=Category.ELECTRONICS_GAMES,
        product="Mario Kart 8 Deluxe",
        platform="Nintendo Switch",
    ),
    "mario-kart-8-switch-game-conditions": ItemFacts(
        category=Category.ELECTRONICS_GAMES,
        product="Mario Kart 8 Deluxe",
        platform="Nintendo Switch",
    ),
    "ps4-slim-console": ItemFacts(
        category=Category.ELECTRONICS_GAMES,
        product="PlayStation 4 Slim console",
        platform="PlayStation 4",
    ),
    "nintendo-switch-console": ItemFacts(
        category=Category.ELECTRONICS_GAMES,
        product="Nintendo Switch console",
        platform="Nintendo Switch",
    ),
    "ring-video-doorbell": ItemFacts(
        category=Category.ELECTRONICS_GAMES, product="Ring Video Doorbell"
    ),
}


def _comp(result: dict[str, Any]) -> Comp:
    extracted = result["price"].get("extracted")
    return Comp(
        item_id=result["product_id"],
        title=result["title"],
        url=result["link"],
        condition=result.get("condition"),
        price_cents=None if extracted is None else round(extracted * 100),
    )


def load_comps(slug: str) -> list[Comp]:
    response = json.loads((FIXTURES / f"{slug}.json").read_text())
    return [_comp(result) for result in response["organic_results"]]
