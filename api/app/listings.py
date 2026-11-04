"""An item's listings on the sales channels, and the sale webhooks the channels send back.

Storing an approved item in app/approval.py publishes it, and the manager route here sends a
refused or failed listing again, such as one whose channel was down for every try.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, col, select

from app.appraisal import SessionDep, _get_item  # pyright: ignore[reportPrivateUsage]
from app.approval import publish_approved
from app.auth import CurrentProfile, ManagerProfile
from app.channels import ChannelError, ChannelsDep
from app.db import SessionFactoryDep
from app.models import Channel, Listing, ListingStatus, SaleSource
from app.sync import record_sale, run_due_jobs, run_jobs

router = APIRouter()


class ListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: Channel
    channel_listing_id: str | None
    status: ListingStatus
    status_detail: str | None
    price_cents: int
    title: str
    approved_at: datetime
    published_at: datetime | None
    sold_at: datetime | None
    ended_at: datetime | None

    @classmethod
    def of(cls, listing: Listing) -> "ListingRead":
        return cls.model_validate(
            {**listing.model_dump(), "title": listing.content.get("title", "")}
        )


def _listings(session: Session, item_id: UUID) -> list[ListingRead]:
    rows = session.exec(
        select(Listing).where(Listing.item_id == item_id).order_by(col(Listing.channel))
    )
    return [ListingRead.of(row) for row in rows]


@router.post("/items/{item_id}/listings", operation_id="publish_item")
def publish(
    item_id: UUID, _: ManagerProfile, session: SessionDep, channels: ChannelsDep
) -> list[ListingRead]:
    """Send a stored item's approved listings to any channel it isn't on yet. Managers only.

    The jobs run before the reply, so the manager sees what each channel said.
    """
    if not channels:
        raise HTTPException(status.HTTP_409_CONFLICT, "No sales channel is set up on this server.")
    item = _get_item(session, item_id)
    # Locked, so two publishes at once can't both make listings.
    session.refresh(item, with_for_update=True)
    job_ids = publish_approved(session, item, channels)
    session.commit()
    run_jobs(session, channels, job_ids=job_ids)
    return _listings(session, item_id)


@router.get("/items/{item_id}/listings", operation_id="list_item_listings")
def list_item_listings(item_id: UUID, _: CurrentProfile, session: SessionDep) -> list[ListingRead]:
    _get_item(session, item_id)
    return _listings(session, item_id)


async def _raw_body(request: Request) -> bytes:
    # The signature covers the exact bytes sent, so they are read before any parsing.
    return await request.body()


@router.post(
    "/channels/{channel}/sales",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
)
def receive_sale(
    channel: Channel,
    body: Annotated[bytes, Depends(_raw_body)],
    background: BackgroundTasks,
    session: SessionDep,
    channels: ChannelsDep,
    factory: SessionFactoryDep,
    signature: Annotated[str | None, Header(alias="X-Channel-Signature")] = None,
) -> None:
    """A channel's sale webhook. A 2xx answer acknowledges the order, so polling skips it."""
    adapter = channels.get(channel)
    if adapter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That channel isn't set up here.")
    if not adapter.verify_signature(body, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That signature doesn't match.")
    try:
        order = adapter.parse_webhook(body)
    except ChannelError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    record_sale(session, channel, order, SaleSource.WEBHOOK)
    session.commit()
    # Take the item down from the other channels straight after answering.
    background.add_task(run_due_jobs, factory, channels)
