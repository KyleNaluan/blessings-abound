"""The plain-language explanation and suggested fix shown with each Needs Attention flag.

Code in app/sync.py finds and flags every conflict and works out what to do about it, which
`template_text` here puts in fixed sentences. The model only rewords those sentences for staff,
from the facts in `PROMPT`. A reply with a number the facts lack, or no usable reply at all,
falls back to the fixed sentences, and a flag shows them until its explanation is written, so a
slow or failed model call never hides one. The scheduler in app/scheduler.py runs
`explain_open_flags` in its own thread, so a slow model never holds up a delist.
"""

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from app.ai import ChatModel, Message, ModelReplyError, complete_json, strip_reply
from app.claims import _numbers  # pyright: ignore[reportPrivateUsage]
from app.listing_drafts import CHANNEL_NAMES
from app.models import (
    Channel,
    ConflictKind,
    DraftSource,
    FallbackReason,
    FlagExplanation,
    Item,
    ItemStatus,
    Listing,
    SaleEvent,
    SyncEvent,
    SyncLogEntry,
)
from app.sync import SOLD_STATUSES, double_sale_orders

logger = logging.getLogger(__name__)

TEXT_MAX = 400
# A tick explains at most this many, so a burst of flags can't keep the thread busy for long.
BATCH = 10

CONFLICT_LABELS = {
    ConflictKind.DOUBLE_SALE: "Double sale",
    ConflictKind.STALE_LISTING: "Stale listing",
    ConflictKind.UNKNOWN_LISTING: "Unknown listing",
}

PROMPT = """\
You explain one problem that a nonprofit thrift store's sales sync found and couldn't settle by \
itself, to the store staff who fix it.
Code has already worked out what happened and what to do, in "Problem" and "Fix" below. Say the \
same things in your own plain words, and change neither.

Facts:
{facts}

Rules:
- Use only the facts, and write no number, price, time or order number that isn't in them.
- Name no step that isn't in "Fix", and don't say anything has been done unless the facts say so.
- Write for someone who isn't technical, with no words such as webhook, API, status or database.
- Use no hashtags, emoji or exclamation marks.

Reply with one JSON object and nothing else, with exactly these keys:
- "explanation": 1 or 2 sentences on what went wrong and why it matters
- "suggested_fix": 1 or 2 sentences on what to do about it
"""

PROMPT_SHA256 = hashlib.sha256(PROMPT.encode()).hexdigest()


class FlagText(BaseModel):
    """An explanation and a suggested fix, from the model or the template."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    explanation: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXT_MAX)
    ]
    suggested_fix: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TEXT_MAX)
    ]


@dataclass(frozen=True)
class FlagContext:
    """What a flag is about, read from the master record as it is now."""

    entry: SyncLogEntry
    title: str | None
    sku: str | None
    item_status: ItemStatus | None
    # For a double sale with two orders still standing: the one that keeps the item and the
    # one the fix cancels.
    keep: SaleEvent | None = None
    cancel: SaleEvent | None = None


def flag_context(session: Session, entry: SyncLogEntry) -> FlagContext:
    listing = session.get(Listing, entry.listing_id) if entry.listing_id else None
    item = session.get(Item, entry.item_id) if entry.item_id else None
    title = str(listing.content.get("title") or "") if listing is not None else ""
    sku = (item.full_sku or item.sku) if item is not None else None
    orders = (
        double_sale_orders(session, item.id)
        if item is not None and entry.conflict == ConflictKind.DOUBLE_SALE
        else None
    )
    keep, cancel = orders or (None, None)
    status = item.status if item is not None else None
    return FlagContext(entry, title or None, sku, status, keep, cancel)


def _channel(channel: Channel | None) -> str:
    return CHANNEL_NAMES[channel] if channel is not None else "The channel"


def template_text(context: FlagContext) -> FlagText:
    """The fixed sentences, which only restate what code found and what it suggests."""
    entry = context.entry
    channel = _channel(entry.channel)
    title = context.title or "The item"
    match entry.conflict:
        case ConflictKind.DOUBLE_SALE if context.keep is not None and context.cancel is not None:
            kept, cancelled = (
                CHANNEL_NAMES[context.keep.channel],
                CHANNEL_NAMES[context.cancel.channel],
            )
            return FlagText(
                explanation=f"{title} sold on {kept} and then again on {cancelled}, but the store "
                "has only one to send.",
                suggested_fix=f"Cancel the {cancelled} order, which refunds that buyer, so the "
                f"{kept} buyer who paid first keeps the item.",
            )
        case ConflictKind.DOUBLE_SALE:
            return FlagText(
                explanation=entry.message,
                suggested_fix="Only one order is left now, so mark this handled.",
            )
        case ConflictKind.STALE_LISTING:
            if context.item_status in SOLD_STATUSES:
                why = "the item has already sold"
            else:
                why = f"Turnstone has that listing as {entry.detail.get('listing_status', 'down')}"
            fix = f"End the listing on {channel} by hand, then mark this handled."
            if entry.detail.get("taking_down"):
                fix = (
                    "Turnstone is already trying again to take it down. If it's still up on "
                    f"{channel} later, end it there by hand and mark this handled."
                )
            return FlagText(
                explanation=f"{title} is still up for sale on {channel}, but {why}, so a buyer "
                "there could pay for something the store can't send.",
                suggested_fix=fix,
            )
        case ConflictKind.UNKNOWN_LISTING if entry.channel_order_id is not None:
            return FlagText(
                explanation=f"{channel} took an order for a listing that isn't in Turnstone, so "
                "the order isn't on the pick list and nobody will pack it.",
                suggested_fix=f"Look up the order on {channel}. If the store has the item, send "
                "it by hand, and if not, cancel the order there. Then mark this handled.",
            )
        case _:
            return FlagText(
                explanation=f"{channel} has a listing up for sale that isn't in Turnstone, so a "
                "sale there wouldn't reach the pick list.",
                suggested_fix=f"Check the listing on {channel} and end it there, unless the "
                "store means to sell it, in which case list it through Turnstone. Then mark this "
                "handled.",
            )


def facts_lines(context: FlagContext, template: FlagText) -> list[str]:
    entry = context.entry
    lines: list[tuple[str, str]] = []
    if entry.conflict is not None:
        lines.append(("Kind of problem", CONFLICT_LABELS[entry.conflict]))
    lines.append(("What Turnstone found", entry.message))
    if entry.channel is not None:
        lines.append(("Channel", CHANNEL_NAMES[entry.channel]))
    if context.title:
        lines.append(("Item", context.title))
    if context.sku:
        lines.append(("SKU", context.sku))
    if context.keep is not None and context.cancel is not None:
        lines.append(("Order that keeps the item", CHANNEL_NAMES[context.keep.channel]))
        lines.append(("Order to cancel", CHANNEL_NAMES[context.cancel.channel]))
    lines.append(("Problem", template.explanation))
    lines.append(("Fix", template.suggested_fix))
    return [f"- {label}: {value}" for label, value in lines]


def build_messages(context: FlagContext, template: FlagText) -> list[Message]:
    facts = "\n".join(facts_lines(context, template))
    return [{"role": "user", "content": PROMPT.format(facts=facts)}]


def parse_text(reply: str) -> FlagText:
    return FlagText.model_validate_json(strip_reply(reply))


def unsupported_numbers(text: FlagText, facts: str) -> list[str]:
    """The numbers in the model's text that the facts don't have, which code refuses."""
    known = _numbers(facts)
    written = _numbers(f"{text.explanation} {text.suggested_fix}")
    return sorted(number for number in written if number not in known)


@dataclass(frozen=True)
class ExplainResult:
    text: FlagText
    source: DraftSource
    fallback_reason: FallbackReason | None
    model_name: str | None = None


def write_text(context: FlagContext, providers: Sequence[ChatModel]) -> ExplainResult:
    """The model's wording when it passes the number check, and the fixed sentences otherwise."""
    template = template_text(context)
    if not providers:
        return ExplainResult(template, DraftSource.TEMPLATE, FallbackReason.NOT_CONFIGURED)
    messages = build_messages(context, template)
    try:
        reply = complete_json(messages, providers, parse_text)
    except ModelReplyError as error:
        logger.warning("explaining flag %s: %s", context.entry.id, error)
        return ExplainResult(template, DraftSource.TEMPLATE, FallbackReason.MODEL_FAILED)
    extra = unsupported_numbers(reply.value, messages[0]["content"])
    if extra:
        logger.warning("explaining flag %s: numbers not in the facts: %s", context.entry.id, extra)
        return ExplainResult(
            template, DraftSource.TEMPLATE, FallbackReason.FLAGGED, model_name=reply.provider
        )
    return ExplainResult(reply.value, DraftSource.MODEL, None, model_name=reply.provider)


def _unexplained(session: Session, limit: int) -> list[UUID]:
    return list(
        session.exec(
            select(SyncLogEntry.id)
            .outerjoin(FlagExplanation, col(FlagExplanation.flag_id) == col(SyncLogEntry.id))
            .where(
                SyncLogEntry.event == SyncEvent.FLAGGED,
                col(SyncLogEntry.resolved_at).is_(None),
                col(FlagExplanation.flag_id).is_(None),
            )
            .order_by(col(SyncLogEntry.created_at))
            .limit(limit)
        ).all()
    )


def explain_flag(session: Session, flag_id: UUID, providers: Sequence[ChatModel]) -> None:
    """Write one flag's explanation, with the model call outside any transaction."""
    entry = session.get_one(SyncLogEntry, flag_id)
    context = flag_context(session, entry)
    session.commit()
    try:
        result = write_text(context, providers)
    except Exception:
        # A bug, not the model, but the flag still gets the fixed sentences instead of none.
        logger.exception("explaining flag %s failed", flag_id)
        result = ExplainResult(
            template_text(context), DraftSource.TEMPLATE, FallbackReason.MODEL_FAILED
        )
    # Two API processes may explain the same flag at once, and the first one written stays.
    session.execute(
        pg_insert(FlagExplanation)
        .values(
            flag_id=flag_id,
            explanation=result.text.explanation,
            suggested_fix=result.text.suggested_fix,
            source=result.source,
            fallback_reason=result.fallback_reason,
            model_name=result.model_name,
        )
        .on_conflict_do_nothing(index_elements=["flag_id"])
    )
    session.commit()


def explain_open_flags(
    session_factory: Callable[[], Session], providers: Sequence[ChatModel]
) -> int:
    """Explain the open flags that have no explanation yet, oldest first, and return how many."""
    with session_factory() as session:
        flag_ids = _unexplained(session, BATCH)
        for flag_id in flag_ids:
            explain_flag(session, flag_id, providers)
    return len(flag_ids)
