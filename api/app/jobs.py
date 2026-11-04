"""Queueing work for the sales channels in `jobs`, which app/sync.py runs.

This holds only what puts rows in the database, with no channel calls, so the approval step in
app/approval.py can queue a publish while app/sync.py calls back into it when a sale arrives.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session, select

from app.channels import ListingContent
from app.models import Channel, Job, JobKind, Listing, ListingStatus

MAX_ATTEMPTS = 10


def utc_now() -> datetime:
    return datetime.now(UTC)


def queue_job(session: Session, kind: JobKind, now: datetime, **payload: str) -> Job:
    job = Job(kind=kind, payload=payload, max_attempts=MAX_ATTEMPTS, run_after=now)
    session.add(job)
    return job


def publish_item(
    session: Session,
    item_id: UUID,
    contents: Mapping[Channel, ListingContent],
    approved_by: UUID,
    approved_at: datetime,
    now: datetime | None = None,
) -> list[UUID]:
    """Queue the item to be listed on each channel, and return the publish jobs to run.

    A channel the item is already pending, active or sold on is left alone, so publishing twice
    makes no second listing. A refused or failed listing is tried again with the new content.
    The caller commits, then runs the jobs with `run_jobs` or leaves them to the scheduler.
    """
    now = now or utc_now()
    existing = {
        listing.channel: listing
        for listing in session.exec(select(Listing).where(Listing.item_id == item_id))
    }
    jobs = []
    for channel, content in contents.items():
        listing = existing.get(channel)
        if listing is not None and listing.status not in (
            ListingStatus.REJECTED,
            ListingStatus.FAILED,
        ):
            continue
        if listing is None:
            listing = Listing(
                item_id=item_id,
                channel=channel,
                price_cents=content.price_cents,
                content={},
                approved_by=approved_by,
                approved_at=approved_at,
            )
        listing.price_cents = content.price_cents
        listing.content = content.model_dump(mode="json")
        listing.status = ListingStatus.PENDING
        listing.status_detail = None
        listing.approved_by = approved_by
        listing.approved_at = approved_at
        session.add(listing)
        session.flush()
        jobs.append(queue_job(session, JobKind.PUBLISH_LISTING, now, listing_id=str(listing.id)))
    session.flush()
    return [job.id for job in jobs]
