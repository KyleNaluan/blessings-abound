"""The Needs Attention screen: the conflicts sync flagged and couldn't settle by itself.

Sync in app/sync.py raises every flag, and app/flag_explanations.py words each one for staff. A
double sale is fixed here in one click, which cancels the later order on its channel through a
cancel job, and any flag can be marked handled once someone has dealt with it by hand. Staff
and managers both work these, because a flag usually needs settling before a manager is in.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, StringConstraints
from sqlmodel import Session, col, select

from app.appraisal import SessionDep
from app.auth import CurrentProfile
from app.channels import ChannelsDep
from app.flag_explanations import FlagContext, flag_context, template_text
from app.jobs import queue_job, utc_now
from app.listing_drafts import CHANNEL_NAMES
from app.models import (
    Channel,
    ConflictKind,
    DraftSource,
    FlagExplanation,
    Job,
    JobKind,
    JobStatus,
    Profile,
    SaleEvent,
    SyncEvent,
    SyncLogEntry,
)
from app.sync import resolve_flag, run_jobs

router = APIRouter()

RESOLVED_SHOWN = 20
NOTE_MAX = 500


class OrderRead(BaseModel):
    channel: Channel
    channel_order_id: str
    price_cents: int
    sold_at: datetime

    @classmethod
    def of(cls, sale: SaleEvent) -> "OrderRead":
        return cls(
            channel=sale.channel,
            channel_order_id=sale.channel_order_id,
            price_cents=sale.price_cents,
            sold_at=sale.sold_at,
        )


class CancelRead(BaseModel):
    """The cancel job for the later order, once someone has pressed the fix."""

    status: JobStatus
    attempts: int
    max_attempts: int
    last_error: str | None


class DoubleSaleRead(BaseModel):
    keep: OrderRead
    cancel: OrderRead
    cancelling: CancelRead | None


class FlagRead(BaseModel):
    id: UUID
    conflict: ConflictKind
    message: str
    channel: Channel | None
    item_id: UUID | None
    sku: str | None
    title: str | None
    channel_listing_id: str | None
    channel_order_id: str | None
    created_at: datetime
    explanation: str
    suggested_fix: str
    # None while the explanation is still being written, which shows the fixed sentences.
    explained_by: DraftSource | None
    double_sale: DoubleSaleRead | None
    resolved_at: datetime | None
    resolved_by: str | None
    resolution: str | None


class AttentionRead(BaseModel):
    open: list[FlagRead]
    # The latest ones only, newest first.
    resolved: list[FlagRead]


def _cancel_job(session: Session, flag_id: UUID) -> Job | None:
    return session.exec(
        select(Job)
        .where(
            Job.kind == JobKind.CANCEL_ORDER,
            col(Job.payload)["flag_id"].astext == str(flag_id),
        )
        .order_by(col(Job.created_at).desc())
        .limit(1)
    ).first()


def _double_sale(session: Session, context: FlagContext) -> DoubleSaleRead | None:
    if context.entry.resolved_at is not None or context.keep is None or context.cancel is None:
        return None
    job = _cancel_job(session, context.entry.id)
    cancelling = None
    if job is not None and job.status != JobStatus.DONE:
        cancelling = CancelRead(
            status=job.status,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            last_error=job.last_error,
        )
    return DoubleSaleRead(
        keep=OrderRead.of(context.keep),
        cancel=OrderRead.of(context.cancel),
        cancelling=cancelling,
    )


def _read(session: Session, entry: SyncLogEntry) -> FlagRead:
    assert entry.conflict is not None
    context = flag_context(session, entry)
    written = session.get(FlagExplanation, entry.id)
    text = template_text(context) if written is None else written
    resolver = session.get(Profile, entry.resolved_by) if entry.resolved_by else None
    return FlagRead(
        id=entry.id,
        conflict=entry.conflict,
        message=entry.message,
        channel=entry.channel,
        item_id=entry.item_id,
        sku=context.sku,
        title=context.title,
        channel_listing_id=entry.channel_listing_id,
        channel_order_id=entry.channel_order_id,
        created_at=entry.created_at,
        explanation=text.explanation,
        suggested_fix=text.suggested_fix,
        explained_by=written.source if written is not None else None,
        double_sale=_double_sale(session, context),
        resolved_at=entry.resolved_at,
        resolved_by=resolver.display_name if resolver is not None else None,
        resolution=entry.resolution,
    )


def _flags(session: Session, *, resolved: bool) -> list[SyncLogEntry]:
    query = select(SyncLogEntry).where(SyncLogEntry.event == SyncEvent.FLAGGED)
    if resolved:
        query = (
            query.where(col(SyncLogEntry.resolved_at).is_not(None))
            .order_by(col(SyncLogEntry.resolved_at).desc())
            .limit(RESOLVED_SHOWN)
        )
    else:
        query = query.where(col(SyncLogEntry.resolved_at).is_(None)).order_by(
            col(SyncLogEntry.created_at).desc()
        )
    return list(session.exec(query).all())


@router.get("/attention", operation_id="list_attention")
def list_attention(_: CurrentProfile, session: SessionDep) -> AttentionRead:
    """The open flags, newest first, and the latest ones someone or sync resolved."""
    return AttentionRead(
        open=[_read(session, entry) for entry in _flags(session, resolved=False)],
        resolved=[_read(session, entry) for entry in _flags(session, resolved=True)],
    )


def _open_flag(session: Session, flag_id: UUID) -> SyncLogEntry:
    """The flag, locked, so two people pressing at once can't both act on it."""
    entry = session.get(SyncLogEntry, flag_id, with_for_update=True)
    if entry is None or entry.event != SyncEvent.FLAGGED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That flag doesn't exist.")
    if entry.resolved_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone has already handled this.")
    return entry


@router.post("/attention/{flag_id}/fix", operation_id="fix_double_sale")
def fix_double_sale(
    flag_id: UUID, profile: CurrentProfile, session: SessionDep, channels: ChannelsDep
) -> FlagRead:
    """Cancel the later order of a double sale on its channel, so the first buyer keeps it.

    The cancel runs before the reply, so the screen shows what the channel said. A channel that
    is down gets the cancel again later, the same way every channel job is retried.
    """
    entry = _open_flag(session, flag_id)
    if entry.conflict != ConflictKind.DOUBLE_SALE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a double sale can be fixed in one click."
        )
    context = flag_context(session, entry)
    if context.cancel is None:
        resolve_flag(
            session,
            entry.id,
            "Only one order was left, so nothing needed cancelling.",
            profile.auth_user_id,
        )
        session.commit()
        return _read(session, entry)
    job = _cancel_job(session, entry.id)
    if job is not None and job.status == JobStatus.PENDING:
        # Already on its way, from an earlier click or one that is still running.
        return _read(session, entry)
    if context.cancel.channel not in channels:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{CHANNEL_NAMES[context.cancel.channel]} isn't set up on this server.",
        )
    job = queue_job(
        session,
        JobKind.CANCEL_ORDER,
        utc_now(),
        listing_id=str(context.cancel.listing_id),
        channel_order_id=context.cancel.channel_order_id,
        flag_id=str(entry.id),
        requested_by=str(profile.auth_user_id),
    )
    session.commit()
    run_jobs(session, channels, job_ids=[job.id])
    session.expire_all()
    return _read(session, session.get_one(SyncLogEntry, flag_id))


class ResolveRequest(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=NOTE_MAX)] = ""


@router.post("/attention/{flag_id}/resolve", operation_id="resolve_flag")
def resolve(
    flag_id: UUID, request: ResolveRequest, profile: CurrentProfile, session: SessionDep
) -> FlagRead:
    """Mark a flag handled after someone dealt with it by hand, with a note on what they did."""
    entry = _open_flag(session, flag_id)
    resolve_flag(session, entry.id, request.note or "Marked handled.", profile.auth_user_id)
    session.commit()
    session.expire_all()
    return _read(session, session.get_one(SyncLogEntry, flag_id))
