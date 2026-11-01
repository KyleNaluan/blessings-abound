"""Photo to item card with a strict JSON reply, one retry on a bad parse, then a second provider.

`ItemCardDraft` is the minimal model for the vision model's part of the item card, with the Stage 1
fields from the project plan. Issue #10 extends it with the staff entries and the endpoint.
"""

import base64
import json
import logging
import re
from dataclasses import dataclass, field

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from app.ai import ChatModel, Message
from app.models import Category, Confidence

logger = logging.getLogger(__name__)

PROMPT = """\
You describe one secondhand item from its photos for a thrift store listing.
Reply with one JSON object and nothing else, using exactly these keys:
- "category": "apparel" or "electronics_games"
- "brand": the brand if it is visible or the product is unmistakable, otherwise null
- "product": a short plain name such as "denim jacket" or "wireless game controller", otherwise null
- "visible_text": text readable on the item itself such as logos, tags or labels, otherwise null
- "search_query": 3 to 8 words for an eBay search, using only brand, product and details that the
  photos show. Never include "new", a style code, a model number or a size that is not readable.
- "model_confidence": "low", "medium" or "high", how sure you are about the brand and product
- "color": main color, otherwise null
- "material": material if it is clear, otherwise null
- "exact_model": exact model or style name only if it is readable or unmistakable, otherwise null
- "platform": the console or system for games and electronics, otherwise null
The items are donated and secondhand, so never describe one as new.
"""


class ItemCardDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category
    brand: str | None = None
    product: str | None = None
    visible_text: str | None = None
    search_query: str
    model_confidence: Confidence
    color: str | None = None
    material: str | None = None
    exact_model: str | None = None
    platform: str | None = None


@dataclass
class Photo:
    data: bytes
    media_type: str = "image/jpeg"


class ItemCardError(RuntimeError):
    """Every provider failed, with one line per attempt in `attempts`."""

    def __init__(self, attempts: list[str]) -> None:
        super().__init__("could not read an item card from the photos: " + "; ".join(attempts))
        self.attempts = attempts


@dataclass
class ItemCardResult:
    card: ItemCardDraft
    provider: str
    # 1 for a first-try success, 2 after the retry.
    attempts_on_provider: int
    used_fallback: bool
    failures: list[str] = field(default_factory=list)


def build_messages(photos: list[Photo], notes: str | None = None) -> list[Message]:
    text = PROMPT if not notes else f"{PROMPT}\nStaff notes: {notes}"
    parts: list[dict] = [{"type": "text", "text": text}]
    for photo in photos:
        encoded = base64.b64encode(photo.data).decode()
        url = f"data:{photo.media_type};base64,{encoded}"
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return [{"role": "user", "content": parts}]


def parse_item_card(reply: str) -> ItemCardDraft:
    """Parse a reply, tolerating a markdown fence or a think block around the JSON."""
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return ItemCardDraft.model_validate_json(text)


def read_item_card(
    photos: list[Photo],
    providers: list[ChatModel],
    notes: str | None = None,
) -> ItemCardResult:
    """Ask each provider in order, giving each one a retry on a bad parse.

    A transport or HTTP error moves straight to the next provider, because a retry of the same
    request would meet the same outage or rate limit.
    """
    messages = build_messages(photos, notes)
    failures: list[str] = []
    for index, provider in enumerate(providers):
        for attempt in (1, 2):
            try:
                reply = provider.complete(messages, json_mode=True)
            except (httpx2.HTTPError, KeyError, IndexError, json.JSONDecodeError) as error:
                failures.append(f"{provider.name} attempt {attempt}: {_describe(error)}")
                break
            try:
                card = parse_item_card(reply)
            except (ValidationError, ValueError) as error:
                failures.append(f"{provider.name} attempt {attempt}: bad JSON ({_describe(error)})")
                continue
            if failures:
                logger.warning("item card needed more than one try: %s", "; ".join(failures))
            return ItemCardResult(card, provider.name, attempt, index > 0, failures)
    raise ItemCardError(failures or ["no provider is configured"])


def _describe(error: Exception) -> str:
    if isinstance(error, httpx2.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, ValidationError):
        return f"{error.error_count()} validation errors"
    return type(error).__name__
