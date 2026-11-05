"""Listing drafts: the model writes a title, description and category per channel from the card.

The model sees the item card and the staff entries only, as the facts in `PROMPT`. The claim
checker in app/claims.py reads its draft, and a flagged draft, or no usable reply at all, falls
back to the fixed template in `template_draft`, which only restates the card. Staff then edit
whichever one they get. The prompt and model are described in docs/architecture.md.
"""

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.ai import ChatModel, Message, ModelReplyError, complete_json, strip_reply
from app.claims import ClaimFlag, ListingFacts, check_listing
from app.models import Category, Channel, Condition, Department, DraftSource, FallbackReason, Flaw

logger = logging.getLogger(__name__)

TITLE_MAX = 80
DESCRIPTION_MAX = 1000

# Each channel's own categories for each kind of item it takes. Channel B takes apparel only.
CHANNEL_CATEGORIES: dict[tuple[Channel, Category], tuple[str, ...]] = {
    (Channel.CHANNEL_A, Category.ELECTRONICS_GAMES): (
        "Video Games",
        "Video Game Consoles",
        "Controllers & Attachments",
        "Video Game Accessories",
    ),
    (Channel.CHANNEL_A, Category.APPAREL): (
        "Men's Clothing",
        "Men's Shoes",
        "Women's Clothing",
        "Women's Shoes",
        "Kids' Clothing",
        "Kids' Shoes",
        "Unisex Clothing",
        "Unisex Shoes",
    ),
    (Channel.CHANNEL_B, Category.APPAREL): (
        "Menswear",
        "Womenswear",
        "Kidswear",
        "Shoes",
        "Unisex",
    ),
}

# The item card fields each channel refuses a listing without, which the mock channels check too.
CHANNEL_REQUIRED: dict[Channel, tuple[str, ...]] = {Channel.CHANNEL_B: ("brand",)}

CHANNEL_NAMES = {Channel.CHANNEL_A: "Channel A", Channel.CHANNEL_B: "Channel B"}

CHANNEL_GUIDES = {
    Channel.CHANNEL_A: "It goes on Channel A, an eBay-style marketplace, so write a plain title "
    "that a buyer would search for, starting with the brand and the item, and a factual "
    "description.",
    Channel.CHANNEL_B: "It goes on Channel B, a Depop-style app for clothing, so write a short, "
    "friendly title and a relaxed description that still sticks to the facts.",
}

CATEGORY_LABELS = {Category.APPAREL: "Apparel", Category.ELECTRONICS_GAMES: "Electronics and games"}
CONDITION_LABELS = {
    Condition.NEW_WITH_TAGS: "New with tags",
    Condition.NEW_WITHOUT_TAGS: "New without tags",
    Condition.PRE_OWNED: "Pre-owned",
}
DEPARTMENT_LABELS = {
    Department.MENS: "Men's",
    Department.WOMENS: "Women's",
    Department.KIDS: "Kids'",
}
FLAW_LABELS = {
    Flaw.STAINS: "stains",
    Flaw.TEARS: "tears",
    Flaw.SCUFFS: "scuffs",
    Flaw.MISSING_PARTS: "missing parts",
}

PROMPT = """\
You write a listing for one secondhand item that a nonprofit thrift store sells online.
{channel_guide}
Use only the facts below, which are everything anyone knows about the item.

Facts:
{facts}

Rules:
- Every brand, model, system, size, color and material you name must appear in the facts.
- Write no number that isn't in the facts, such as a year, a count, a storage size or a measurement.
- Give the condition only as "{condition}", and say nothing else about wear, quality or \
cleanliness, such as "excellent", "like new", "clean" or "no flaws".
{item_rules}
- Name no size, fit or department that isn't in the facts, and don't say who the item is for.
- Never use the words rare, authentic, genuine, antique, vintage, collectible, official, licensed, \
OEM, limited edition, guaranteed or smoke-free.
- Don't mention price, value, shipping, the store or where the item came from, and use no \
hashtags or emoji.

Reply with one JSON object and nothing else, with exactly these keys:
- "title": at most {title_max} characters
- "description": 2 to 4 sentences
- "category": one of these, copied exactly: {categories}
"""

PROMPT_SHA256 = hashlib.sha256(PROMPT.encode()).hexdigest()


def channel_takes(channel: Channel, category: Category) -> bool:
    return (channel, category) in CHANNEL_CATEGORIES


def category_options(channel: Channel, category: Category) -> tuple[str, ...]:
    return CHANNEL_CATEGORIES.get((channel, category), ())


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def facts_lines(facts: ListingFacts) -> list[str]:
    """The facts as the model reads them, leaving out anything nobody recorded."""
    lines = [("Category", CATEGORY_LABELS[facts.category])]
    for label, value in (
        ("Brand", facts.brand),
        ("Product", facts.product),
        ("Exact model", facts.exact_model),
        ("Platform", facts.platform),
        ("Color", facts.color),
        ("Material", facts.material),
        ("Text on the item", facts.visible_text),
    ):
        if value:
            lines.append((label, value))
    if facts.department:
        lines.append(("Department", DEPARTMENT_LABELS[facts.department]))
    if facts.size:
        lines.append(("Size", facts.size))
    if facts.size_type:
        lines.append(("Size type", facts.size_type))
    lines.append(("Condition", CONDITION_LABELS[facts.condition]))
    if facts.flaws:
        lines.append(("Flaws", ", ".join(FLAW_LABELS[flaw] for flaw in facts.flaws)))
    if facts.category is Category.ELECTRONICS_GAMES:
        working = "not recorded" if facts.tested_working is None else _yes_no(facts.tested_working)
        lines.append(("Tested and working", working))
        if facts.complete_in_box is not None:
            lines.append(("Complete in box", _yes_no(facts.complete_in_box)))
    if facts.accessories_included:
        lines.append(("Accessories included", facts.accessories_included))
    return [f"- {label}: {value}" for label, value in lines]


def _item_rules(facts: ListingFacts) -> list[str]:
    if facts.flaws:
        flaws = ", ".join(FLAW_LABELS[flaw] for flaw in facts.flaws)
        rules = [f"- Mention these flaws plainly: {flaws}, and no others."]
    else:
        rules = ["- Don't mention flaws, and don't say it has none."]
    if facts.category is Category.ELECTRONICS_GAMES:
        if facts.tested_working:
            rules.append("- You may say it is tested and working.")
        else:
            rules.append("- Don't say it works, was tested, powers on or plays.")
    if facts.complete_in_box:
        rules.append("- You may say it is complete in box.")
    if facts.accessories_included:
        rules.append('- Say what it comes with only from "Accessories included".')
    if not facts.complete_in_box and not facts.accessories_included:
        rules.append(
            "- Don't mention a box, a manual, packaging or anything it comes with, and don't use "
            'the words "includes", "including" or "comes with" at all.'
        )
    if facts.visible_text:
        rules.append(
            "- To give the text on the item, write It reads and then the text in double quotes, "
            "copied exactly."
        )
    return rules


def build_prompt(facts: ListingFacts, channel: Channel) -> str:
    options = category_options(channel, facts.category)
    return PROMPT.format(
        channel_guide=CHANNEL_GUIDES[channel],
        facts="\n".join(facts_lines(facts)),
        condition=CONDITION_LABELS[facts.condition],
        item_rules="\n".join(_item_rules(facts)),
        title_max=TITLE_MAX,
        categories=", ".join(f'"{option}"' for option in options),
    )


def build_messages(facts: ListingFacts, channel: Channel) -> list[Message]:
    return [{"role": "user", "content": build_prompt(facts, channel)}]


class DraftText(BaseModel):
    """A title, description and category, from the model or the template."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX)
    ]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=DESCRIPTION_MAX)
    ]
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def parse_draft(reply: str, options: Sequence[str]) -> DraftText:
    """Parse a reply, which must pick one of the channel's categories."""
    draft = DraftText.model_validate_json(strip_reply(reply))
    chosen = next((option for option in options if option.lower() == draft.category.lower()), None)
    if chosen is None:
        raise ValueError(f"category {draft.category!r} is not one of the channel's")
    return draft.model_copy(update={"category": chosen})


_CONTROLLER = re.compile(
    r"\b(?:controllers?|joy[- ]?cons?|gamepads?|remotes?|wiimote|joysticks?|guitar|drums?"
    r"|balance board|steering wheel|light gun|zapper)\b",
    re.IGNORECASE,
)
_CONSOLE = re.compile(r"\b(?:consoles?|systems?|handhelds?)\b", re.IGNORECASE)
_SHOE = re.compile(
    r"\b(?:shoes?|sneakers?|boots?|sandals?|heels|loafers?|trainers?|cleats?|slippers?|clogs?)\b",
    re.IGNORECASE,
)


CHANNEL_B_DEPARTMENTS: dict[Department | None, str] = {
    Department.MENS: "Menswear",
    Department.WOMENS: "Womenswear",
    Department.KIDS: "Kidswear",
    None: "Unisex",
}


def default_category(facts: ListingFacts, channel: Channel) -> str:
    """The template's category, from the card alone."""
    named = " ".join(part for part in (facts.product, facts.exact_model) if part)
    if facts.category is Category.ELECTRONICS_GAMES:
        if _CONTROLLER.search(named):
            return "Controllers & Attachments"
        if _CONSOLE.search(named):
            return "Video Game Consoles"
        if re.search(r"\bgames?\b|\bcartridge\b|\bdisc\b", named, re.IGNORECASE):
            return "Video Games"
        return "Video Game Accessories"
    shoes = bool(_SHOE.search(named))
    if channel is Channel.CHANNEL_B:
        if shoes:
            return "Shoes"
        return CHANNEL_B_DEPARTMENTS[facts.department]
    department = DEPARTMENT_LABELS[facts.department] if facts.department else "Unisex"
    return f"{department} {'Shoes' if shoes else 'Clothing'}"


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _contains(text: str, part: str) -> bool:
    return part.lower() in text.lower()


def _item_name(facts: ListingFacts) -> str:
    """The brand and the most specific name for the item, without repeating either."""
    name = facts.exact_model or facts.product or facts.platform or "item"
    if facts.brand and not _contains(name, facts.brand):
        name = f"{facts.brand} {name}"
    # A console is its platform, so only games and accessories say which system they are for.
    console = bool(_CONSOLE.search(" ".join(filter(None, (facts.product, facts.exact_model)))))
    if facts.platform and not console and not _contains(name, facts.platform):
        name = f"{name} for {facts.platform}"
    return _capitalize(name)


def _fit(parts: list[str], suffix: str) -> str:
    """Join the parts and the suffix, dropping parts from the end until it fits the title."""
    while parts:
        title = f"{', '.join(parts)} - {suffix}"
        if len(title) <= TITLE_MAX:
            return title
        if len(parts) == 1:
            room = TITLE_MAX - len(suffix) - 3
            return f"{parts[0][:room].rsplit(' ', 1)[0]} - {suffix}"
        parts = parts[:-1]
    return suffix


def template_draft(facts: ListingFacts, channel: Channel) -> DraftText:
    """The fixed template, which restates the card and so never makes a claim of its own."""
    name = _item_name(facts)
    condition = CONDITION_LABELS[facts.condition]
    department = DEPARTMENT_LABELS[facts.department] if facts.department else None
    title_parts = [f"{department} {name}" if department else name]
    size = " ".join(part for part in (facts.size_type, facts.size) if part) or None
    if size:
        title_parts.append(f"Size {size}")
    if facts.color:
        title_parts.append(_capitalize(facts.color))

    sentences = [f"{name}, {condition.lower()}."]
    for label, value in (
        ("Color", facts.color),
        ("Material", facts.material),
        ("Department", department),
        ("Size", size),
    ):
        if value:
            sentences.append(f"{label}: {value}.")
    if facts.flaws:
        sentences.append(f"Flaws: {', '.join(FLAW_LABELS[flaw] for flaw in facts.flaws)}.")
    if facts.tested_working is True:
        sentences.append("Tested and working.")
    elif facts.tested_working is False:
        sentences.append("Not confirmed working.")
    if facts.complete_in_box is True:
        sentences.append("Complete in box.")
    if facts.accessories_included:
        sentences.append(f"Includes: {facts.accessories_included}.")
    sentences.append("See the photos for the exact item.")
    return DraftText(
        title=_fit(title_parts, condition),
        description=" ".join(sentences)[:DESCRIPTION_MAX],
        category=default_category(facts, channel),
    )


@dataclass
class DraftResult:
    text: DraftText
    source: DraftSource
    fallback_reason: FallbackReason | None
    model_name: str | None = None
    model_flags: list[ClaimFlag] = field(default_factory=list)


def write_draft(
    facts: ListingFacts, channel: Channel, providers: Sequence[ChatModel]
) -> DraftResult:
    """The model's draft when the checker passes it, and the template otherwise."""
    if not channel_takes(channel, facts.category):
        raise ValueError(f"{channel.value} doesn't take {facts.category.value}")
    template = template_draft(facts, channel)
    if not providers:
        return DraftResult(template, DraftSource.TEMPLATE, FallbackReason.NOT_CONFIGURED)
    options = category_options(channel, facts.category)
    try:
        reply = complete_json(
            build_messages(facts, channel), providers, lambda text: parse_draft(text, options)
        )
    except ModelReplyError as error:
        logger.warning("listing draft for %s: %s", channel.value, error)
        return DraftResult(template, DraftSource.TEMPLATE, FallbackReason.MODEL_FAILED)
    draft = reply.value
    flags = check_listing(draft.title, draft.description, facts)
    if flags:
        return DraftResult(
            template,
            DraftSource.TEMPLATE,
            FallbackReason.FLAGGED,
            model_name=reply.provider,
            model_flags=flags,
        )
    return DraftResult(draft, DraftSource.MODEL, None, model_name=reply.provider)
