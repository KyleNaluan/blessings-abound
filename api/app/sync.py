"""Keeping the master record and the sales channels in step.

The master record in Postgres is the truth, and a channel is changed only through a job in
`jobs`, so a call that fails is tried again later instead of being lost. The flow is:

- `publish_item` in app/jobs.py makes a pending listing and a publish job for each channel, which
  the storage step in app/approval.py calls once an approved item has its shelf or bin.
- `record_sale` takes one order from a webhook or from polling, marks the item sold with
  `mark_sold`, which puts it on the pick list, and queues an end job for every other active
  listing of that item, or flags a double sale.
- `poll_channel` asks a channel for the orders the app hasn't acknowledged, which catches a
  webhook that never arrived, and checks its active listings against the master record.
- `run_due_jobs` runs whatever is due, and app/scheduler.py calls it every few seconds.

Every change goes in `sync_log`, and a conflict the app can't settle on its own is a flag there,
with the shape in docs/database.md, for the Needs Attention screen in #43.
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from app.approval import mark_sold
from app.channels import (
    ChannelAdapter,
    ChannelError,
    ChannelOrder,
    ChannelRejectedError,
    Channels,
    ChannelUnavailableError,
    ListingAlreadySoldError,
    ListingContent,
    ListingNotFoundError,
)
from app.jobs import queue_job, utc_now
from app.listing_drafts import CHANNEL_NAMES
from app.models import (
    Channel,
    ConflictKind,
    Item,
    ItemStatus,
    Job,
    JobKind,
    JobStatus,
    Listing,
    ListingStatus,
    SaleEvent,
    SaleSource,
    SyncEvent,
    SyncLogEntry,
)

logger = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300
# Longer than any one channel call, so a job is never run twice at once.
LEASE_SECONDS = 60
# Items that have sold, so another sale of the same item is a double sale.
SOLD_STATUSES = {ItemStatus.SOLD, ItemStatus.PICKED}

SessionFactory = Callable[[], Session]


def retry_delay(attempts: int) -> timedelta:
    """The wait after a failed try, doubling from 5 seconds up to 5 minutes."""
    return timedelta(seconds=min(RETRY_BASE_SECONDS * 2 ** (attempts - 1), RETRY_MAX_SECONDS))


def log(session: Session, event: SyncEvent, message: str, **fields: Any) -> None:
    session.add(SyncLogEntry(event=event, message=message, **fields))


def flag(session: Session, conflict: ConflictKind, key: str, message: str, **fields: Any) -> bool:
    """Raise a Needs Attention flag, unless one with the same key is still open."""
    values = {
        "id": uuid4(),
        "event": SyncEvent.FLAGGED,
        "conflict": conflict,
        "conflict_key": key,
        "message": message,
        **fields,
    }
    inserted = session.execute(
        pg_insert(SyncLogEntry)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["conflict_key"],
            index_where=sa.text("conflict_key IS NOT NULL AND resolved_at IS NULL"),
        )
        .returning(col(SyncLogEntry.id))
    ).first()
    if inserted is not None:
        logger.warning("Needs attention: %s", message)
    return inserted is not None


def _resolve_flags(session: Session, conflict: ConflictKind, key: str, resolution: str) -> None:
    """Close an open flag that sync has settled itself, such as a stale listing it took down."""
    session.execute(
        sa.update(SyncLogEntry)
        .where(
            col(SyncLogEntry.conflict) == conflict,
            col(SyncLogEntry.conflict_key) == key,
            col(SyncLogEntry.resolved_at).is_(None),
        )
        .values(resolved_at=sa.func.now(), resolution=resolution)
    )


def _label(channel: Channel) -> str:
    return CHANNEL_NAMES[channel]


def _title(listing: Listing) -> str:
    return str(listing.content.get("title") or "the item")


# Publishing


def _publish(session: Session, job: Job, channels: Channels, now: datetime) -> None:
    listing = session.get(Listing, UUID(job.payload["listing_id"]))
    if listing is None or listing.status != ListingStatus.PENDING:
        return
    item = session.get_one(Item, listing.item_id)
    if item.status in SOLD_STATUSES:
        listing.status = ListingStatus.ENDED
        listing.ended_at = now
        listing.status_detail = "The item sold before it was listed here."
        session.add(listing)
        log(
            session,
            SyncEvent.PUBLISH_SKIPPED,
            f"{_title(listing)} sold before it was listed on {_label(listing.channel)}.",
            channel=listing.channel,
            item_id=item.id,
            listing_id=listing.id,
        )
        return
    adapter = _adapter(channels, listing.channel)
    content = ListingContent.model_validate(listing.content)
    listing_id, item_id = listing.id, listing.item_id
    # The channel call is made with no row locked, and the session lets go of its transaction.
    session.commit()
    try:
        published = adapter.publish(listing_id, content)
    except ChannelRejectedError as error:
        _finish_publish_refused(session, listing_id, str(error))
        return
    item = session.get_one(Item, item_id, with_for_update=True)
    listing = session.get_one(Listing, listing_id, with_for_update=True)
    listing.channel_listing_id = published.id
    listing.published_at = listing.published_at or now
    if listing.status == ListingStatus.PENDING:
        listing.status = ListingStatus.ACTIVE
    session.add(listing)
    log(
        session,
        SyncEvent.PUBLISHED,
        f"{_title(listing)} is listed on {_label(listing.channel)}.",
        channel=listing.channel,
        item_id=item.id,
        listing_id=listing.id,
        channel_listing_id=published.id,
    )
    if item.status in SOLD_STATUSES:
        # It sold elsewhere while this channel was publishing, so take it straight back down.
        queue_job(session, JobKind.END_LISTING, now, listing_id=str(listing.id))
    elif item.status is ItemStatus.APPROVED:
        item.status = ItemStatus.LISTED
        session.add(item)


def _finish_publish_refused(session: Session, listing_id: UUID, reason: str) -> None:
    listing = session.get_one(Listing, listing_id, with_for_update=True)
    listing.status = ListingStatus.REJECTED
    listing.status_detail = reason
    session.add(listing)
    log(
        session,
        SyncEvent.PUBLISH_REJECTED,
        f"{_label(listing.channel)} refused {_title(listing)}. {reason}",
        channel=listing.channel,
        item_id=listing.item_id,
        listing_id=listing.id,
    )


# Ending a listing after a sale elsewhere


def _end(session: Session, job: Job, channels: Channels, now: datetime) -> None:
    listing = session.get(Listing, UUID(job.payload["listing_id"]))
    if listing is None or listing.status != ListingStatus.ACTIVE:
        return
    if listing.channel_listing_id is None:
        # Only a pending publish lacks the channel's id, and that publish ends it when it lands.
        return
    adapter = _adapter(channels, listing.channel)
    listing_id, channel_listing_id = listing.id, listing.channel_listing_id
    session.commit()
    try:
        adapter.end_listing(channel_listing_id)
    except ListingAlreadySoldError:
        # It sold on this channel too before it came down. Polling records that sale now, which
        # flags the double sale, rather than waiting for a webhook that may not come.
        listing = session.get_one(Listing, listing_id)
        log(
            session,
            SyncEvent.DELIST_FOUND_SOLD,
            f"{_title(listing)} had already sold on {_label(listing.channel)} "
            "when Turnstone went to take it down.",
            channel=listing.channel,
            item_id=listing.item_id,
            listing_id=listing.id,
            channel_listing_id=channel_listing_id,
        )
        session.commit()
        poll_orders(session, adapter, now)
        return
    except ListingNotFoundError:
        pass
    listing = session.get_one(Listing, listing_id, with_for_update=True)
    if listing.status != ListingStatus.ACTIVE:
        return
    listing.status = ListingStatus.ENDED
    listing.ended_at = now
    session.add(listing)
    log(
        session,
        SyncEvent.DELISTED,
        f"{_title(listing)} came down from {_label(listing.channel)}.",
        channel=listing.channel,
        item_id=listing.item_id,
        listing_id=listing.id,
        channel_listing_id=channel_listing_id,
    )
    _resolve_flags(
        session,
        ConflictKind.STALE_LISTING,
        _stale_key(listing.channel, channel_listing_id),
        "Turnstone took the listing down.",
    )


def _adapter(channels: Channels, channel: Channel) -> ChannelAdapter:
    adapter = channels.get(channel)
    if adapter is None:
        raise ChannelUnavailableError(f"{_label(channel)} isn't set up on this server.")
    return adapter


# Sales


def record_sale(
    session: Session,
    channel: Channel,
    order: ChannelOrder,
    source: SaleSource,
    now: datetime | None = None,
) -> None:
    """Record one order, once, however many times the webhook and polling report it.

    The caller commits, and acknowledges the order to the channel after that.
    """
    now = now or utc_now()
    listing = _listing_for_ref(session, channel, order.external_ref)
    if listing is None:
        flag(
            session,
            ConflictKind.UNKNOWN_LISTING,
            f"unknown_listing:{channel.value}:order:{order.id}",
            f"{_label(channel)} sold a listing Turnstone has no record of.",
            channel=channel,
            channel_listing_id=order.listing_id,
            channel_order_id=order.id,
            source=source,
            detail=_order_detail(order),
        )
        return
    item = session.get_one(Item, listing.item_id, with_for_update=True)
    listing = session.get_one(Listing, listing.id, with_for_update=True)
    inserted = session.execute(
        pg_insert(SaleEvent)
        .values(
            id=uuid4(),
            item_id=item.id,
            listing_id=listing.id,
            channel=channel,
            channel_order_id=order.id,
            price_cents=order.price_cents,
            sold_at=order.sold_at,
            source=source,
        )
        .on_conflict_do_nothing(index_elements=["channel", "channel_order_id"])
        .returning(col(SaleEvent.id))
    ).first()
    if inserted is None:
        return
    listing.status = ListingStatus.SOLD
    listing.sold_at = order.sold_at
    listing.channel_listing_id = listing.channel_listing_id or order.listing_id
    session.add(listing)
    log(
        session,
        SyncEvent.SALE_RECORDED,
        f"{_title(listing)} sold on {_label(channel)}.",
        channel=channel,
        item_id=item.id,
        listing_id=listing.id,
        channel_listing_id=order.listing_id,
        channel_order_id=order.id,
        source=source,
        detail=_order_detail(order),
    )
    if item.status in SOLD_STATUSES:
        _flag_double_sale(session, item, listing, order, source)
        return
    if item.status is ItemStatus.APPROVED:
        # It sold before the channel's answer to the publish came back, so it was listed.
        item.status = ItemStatus.LISTED
    mark_sold(session, item.id)
    others = session.exec(
        select(Listing).where(
            Listing.item_id == item.id,
            Listing.id != listing.id,
            col(Listing.status).in_([ListingStatus.ACTIVE, ListingStatus.PENDING]),
        )
    )
    for other in others:
        if other.status == ListingStatus.ACTIVE:
            queue_job(session, JobKind.END_LISTING, now, listing_id=str(other.id))
        # A pending publish sees the sold item and stops on its own.


def _flag_double_sale(
    session: Session, item: Item, listing: Listing, order: ChannelOrder, source: SaleSource
) -> None:
    earlier = session.exec(
        select(SaleEvent)
        .where(SaleEvent.item_id == item.id, SaleEvent.listing_id != listing.id)
        .order_by(col(SaleEvent.sold_at))
    ).all()
    others = " and ".join(dict.fromkeys(_label(sale.channel) for sale in earlier))
    flag(
        session,
        ConflictKind.DOUBLE_SALE,
        f"double_sale:{listing.channel.value}:{order.id}",
        f"{_title(listing)} sold on {others} and again on {_label(listing.channel)}, so one "
        "of the orders needs cancelling.",
        channel=listing.channel,
        item_id=item.id,
        listing_id=listing.id,
        channel_listing_id=listing.channel_listing_id,
        channel_order_id=order.id,
        source=source,
        detail={
            **_order_detail(order),
            "other_orders": [
                {
                    "channel": sale.channel.value,
                    "channel_order_id": sale.channel_order_id,
                    "listing_id": str(sale.listing_id),
                    "price_cents": sale.price_cents,
                    "sold_at": sale.sold_at.isoformat(),
                }
                for sale in earlier
            ],
        },
    )


def _order_detail(order: ChannelOrder) -> dict[str, Any]:
    return {
        "external_ref": order.external_ref,
        "price_cents": order.price_cents,
        "sold_at": order.sold_at.isoformat(),
    }


def _listing_for_ref(session: Session, channel: Channel, external_ref: str) -> Listing | None:
    try:
        listing_id = UUID(external_ref)
    except ValueError:
        return None
    listing = session.get(Listing, listing_id)
    return listing if listing is not None and listing.channel == channel else None


# Polling


@dataclass
class PollResult:
    orders: int = 0
    flags: int = 0


def poll_orders(session: Session, adapter: ChannelAdapter, now: datetime) -> int:
    """Record the orders the channel says the app hasn't acknowledged, and return how many."""
    orders = adapter.unacknowledged_orders()
    for order in orders:
        record_sale(session, adapter.name, order, SaleSource.POLLING, now)
        session.commit()
        adapter.acknowledge_order(order.id)
    return len(orders)


def poll_channel(
    session: Session, adapter: ChannelAdapter, now: datetime | None = None
) -> PollResult:
    """Catch sales whose webhook never arrived, then compare the channel's listings with ours."""
    now = now or utc_now()
    result = PollResult(orders=poll_orders(session, adapter, now))
    pending_ends = {
        UUID(job.payload["listing_id"])
        for job in session.exec(
            select(Job).where(Job.kind == JobKind.END_LISTING, Job.status == JobStatus.PENDING)
        )
    }
    for remote in adapter.active_listings():
        listing = _listing_for_ref(session, adapter.name, remote.external_ref)
        if listing is None:
            result.flags += flag(
                session,
                ConflictKind.UNKNOWN_LISTING,
                f"unknown_listing:{adapter.name.value}:listing:{remote.id}",
                f"{_label(adapter.name)} has a live listing Turnstone has no record of.",
                channel=adapter.name,
                channel_listing_id=remote.id,
                detail={"external_ref": remote.external_ref, "price_cents": remote.price_cents},
            )
            continue
        if listing.status == ListingStatus.PENDING or listing.id in pending_ends:
            # The publish or end job that is still due settles it.
            continue
        item = session.get_one(Item, listing.item_id)
        if listing.status == ListingStatus.ACTIVE and item.status not in SOLD_STATUSES:
            continue
        # Live on the channel while the master record says it should be down.
        taking_down = listing.status == ListingStatus.ACTIVE
        message = (
            f"{_title(listing)} is still live on {_label(adapter.name)}, but Turnstone has the "
            f"listing as {listing.status.value} and the item as {item.status.value}."
        )
        if taking_down:
            message += " Turnstone is trying again to take it down."
            queue_job(session, JobKind.END_LISTING, now, listing_id=str(listing.id))
        result.flags += flag(
            session,
            ConflictKind.STALE_LISTING,
            _stale_key(adapter.name, remote.id),
            message,
            channel=adapter.name,
            item_id=listing.item_id,
            listing_id=listing.id,
            channel_listing_id=remote.id,
            detail={
                "listing_status": listing.status.value,
                "item_status": item.status.value,
                "price_cents": remote.price_cents,
                "taking_down": taking_down,
            },
        )
    session.commit()
    return result


def _stale_key(channel: Channel, channel_listing_id: str) -> str:
    return f"stale_listing:{channel.value}:{channel_listing_id}"


def poll_channels(session_factory: SessionFactory, channels: Channels) -> None:
    for adapter in channels.values():
        with session_factory() as session:
            try:
                poll_channel(session, adapter)
            except ChannelError as error:
                logger.info("Polling %s failed: %s", _label(adapter.name), error)


# Jobs


def _claim(session: Session, now: datetime, job_ids: Iterable[UUID] | None) -> Job | None:
    """Take one due job, pushing it forward by a lease so no other runner takes it meanwhile."""
    due = (
        select(Job.id)
        .where(Job.status == JobStatus.PENDING, col(Job.run_after) <= now)
        .order_by(col(Job.run_after))
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job_ids is not None:
        due = due.where(col(Job.id).in_(list(job_ids)))
    job_id = session.exec(due).first()
    if job_id is None:
        return None
    job = session.get_one(Job, job_id)
    job.attempts += 1
    job.run_after = now + timedelta(seconds=LEASE_SECONDS)
    session.add(job)
    session.commit()
    return job


def run_jobs(
    session: Session,
    channels: Channels,
    now: datetime | None = None,
    job_ids: Iterable[UUID] | None = None,
) -> int:
    """Run the due jobs, or only those given, and return how many ran."""
    now = now or utc_now()
    ids = list(job_ids) if job_ids is not None else None
    ran = 0
    while (job := _claim(session, now, ids)) is not None:
        ran += 1
        _run(session, job, channels, now)
    return ran


def _run(session: Session, job: Job, channels: Channels, now: datetime) -> None:
    job_id = job.id
    try:
        if job.kind == JobKind.PUBLISH_LISTING:
            _publish(session, job, channels, now)
        else:
            _end(session, job, channels, now)
    except Exception as error:
        session.rollback()
        if not isinstance(error, ChannelError):
            # A bug, not the channel, but it is retried the same way so the job isn't lost.
            logger.exception("Job %s failed", job_id)
            error = ChannelError(f"Turnstone hit an error: {error}")
        _retry_or_give_up(session, job_id, str(error), now)
        session.commit()
        return
    job = session.get_one(Job, job_id)
    job.status = JobStatus.DONE
    job.last_error = None
    session.add(job)
    session.commit()


def _retry_or_give_up(session: Session, job_id: UUID, error: str, now: datetime) -> None:
    job = session.get_one(Job, job_id, with_for_update=True)
    job.last_error = error
    listing = session.get(Listing, UUID(job.payload["listing_id"]))
    publishing = job.kind == JobKind.PUBLISH_LISTING
    fields: dict[str, Any] = {}
    if listing is not None:
        fields = {"channel": listing.channel, "item_id": listing.item_id, "listing_id": listing.id}
    title = _title(listing) if listing is not None else "A listing"
    if job.attempts < job.max_attempts:
        job.run_after = now + retry_delay(job.attempts)
        event = SyncEvent.PUBLISH_FAILED if publishing else SyncEvent.DELIST_FAILED
        action = "Listing" if publishing else "Taking down"
        message = f"{action} {title} failed, try {job.attempts} of {job.max_attempts}. {error}"
    else:
        job.status = JobStatus.FAILED
        event = SyncEvent.PUBLISH_GAVE_UP if publishing else SyncEvent.DELIST_GAVE_UP
        if publishing and listing is not None and listing.status == ListingStatus.PENDING:
            listing.status = ListingStatus.FAILED
            listing.status_detail = error
            session.add(listing)
        # A listing that never came down is found by polling as a stale listing.
        action = "listing" if publishing else "taking down"
        message = f"Turnstone stopped {action} {title} after {job.attempts} tries. {error}"
    session.add(job)
    log(session, event, message, detail={"job_id": str(job.id)}, **fields)


def run_due_jobs(session_factory: SessionFactory, channels: Channels) -> int:
    with session_factory() as session:
        return run_jobs(session, channels)
