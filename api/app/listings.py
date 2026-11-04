"""Listing an item on the sales channels, and the sale webhooks the channels send back.

The manager route here, and app/publish_to_channels.py beside it, stand in for #42's approval
screen, so a manager can publish an item for testing and the demo. #42 calls `publish_item` in
app/sync.py the same way.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, col, select

from app.appraisal import SessionDep, _get_item, _require_status
from app.auth import CurrentProfile, ManagerProfile
from app.channels import ChannelError, Channels, get_channels
from app.db import get_session_factory
from app.models import (
    Appraisal,
    ChannelName,
    Decision,
    DecisionChoice,
    ItemCard,
    ItemStatus,
    Listing,
    ListingStatus,
    Profile,
    SaleSource,
)
from app.pipeline import placeholder_listing_content
from app.sync import publish_item, record_sale, run_due_jobs, run_jobs

router = APIRouter()

ChannelsDep = Annotated[Channels, Depends(get_channels)]
SessionFactoryDep = Annotated[Callable[[], Session], Depends(get_session_factory)]

# An item can be listed once a yes decision stands, and listed on more channels after that.
PUBLISHABLE = {ItemStatus.APPRAISED, ItemStatus.APPROVED, ItemStatus.LISTED}


class PublishRequest(BaseModel):
    # Every channel set up on this server when left out.
    channels: list[ChannelName] | None = Field(default=None, min_length=1)
    # The appraisal's typical price when left out.
    price_cents: int | None = Field(default=None, gt=0)


class ListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: ChannelName
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


def _price(session: Session, item_id: UUID, requested: int | None) -> int:
    if requested is not None:
        return requested
    appraisal = session.exec(
        select(Appraisal)
        .where(Appraisal.item_id == item_id)
        .order_by(col(Appraisal.created_at).desc())
    ).first()
    if appraisal is None or not appraisal.price_typical_cents:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This item has no appraised price, so give a price to list it at.",
        )
    return appraisal.price_typical_cents


def _require_yes(session: Session, item_id: UUID) -> None:
    decision = session.exec(
        select(Decision)
        .where(Decision.item_id == item_id)
        .order_by(col(Decision.decided_at).desc())
    ).first()
    if decision is None or decision.decision != DecisionChoice.YES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only an item with a yes decision can be listed."
        )


def publish_listings(
    session: Session,
    item_id: UUID,
    request: PublishRequest,
    manager: Profile,
    channels: Channels,
) -> list[ListingRead]:
    """List the item on the channels for a manager, which the route and the script both do."""
    item = _get_item(session, item_id)
    # Locked, so two approvals at once can't both make listings.
    session.refresh(item, with_for_update=True)
    _require_status(item, PUBLISHABLE, "listed")
    if item.status == ItemStatus.APPRAISED:
        _require_yes(session, item_id)
    names = request.channels or list(channels)
    if not names:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "No sales channels are set up on this server."
        )
    card = session.get(ItemCard, item_id)
    if card is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no card to list from.")
    content = placeholder_listing_content(card, _price(session, item_id, request.price_cents))
    job_ids = publish_item(session, item, dict.fromkeys(names, content), manager.auth_user_id)
    session.commit()
    # Publish now so the manager sees the result, and a channel that is down is retried later.
    run_jobs(session, channels, job_ids=job_ids)
    return _listings(session, item_id)


@router.post("/items/{item_id}/listings", operation_id="publish_item")
def publish(
    item_id: UUID,
    request: PublishRequest,
    manager: ManagerProfile,
    session: SessionDep,
    channels: ChannelsDep,
) -> list[ListingRead]:
    """List the item on the channels, as #42's approval will. Managers only."""
    return publish_listings(session, item_id, request, manager, channels)


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
    channel: ChannelName,
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
