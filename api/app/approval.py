"""The manager's step after drafting, the storage step after approval, and the pick list.

A manager reviews the listing drafts staff sent on, may set a price per channel in place of the
appraisal's typical price, and approves or rejects the item. Channel A needs the package weight and
box size before approval, and every approved item gets them and a shelf or bin code when stored.
A sold item is on the pick list until someone picks it.
"""

import re
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlmodel import Session, col, select

from app.appraisal import (
    _get_item,  # pyright: ignore[reportPrivateUsage]
    _item_drafts,  # pyright: ignore[reportPrivateUsage]
    _require_status,  # pyright: ignore[reportPrivateUsage]
    latest_decision,
)
from app.auth import CurrentProfile, ManagerProfile
from app.claims import ClaimFlag, ListingFacts, check_listing
from app.db import get_session
from app.listing_drafts import CHANNEL_NAMES
from app.models import (
    Appraisal,
    Category,
    Channel,
    Condition,
    Confidence,
    Decision,
    DecisionChoice,
    DraftState,
    Item,
    ItemCard,
    ItemStatus,
    ListingDraft,
    Profile,
    Recommendation,
)
from app.store_settings import StoreSettings, read_store_settings

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]

# The statuses of an approved item that is not yet published, which the storage step works on.
STORABLE = {ItemStatus.APPROVED, ItemStatus.HELD_FOR_SEASON}
LOCATION_PATTERN = re.compile(r"^[A-Z0-9]+(?:[ -][A-Z0-9]+)*$")
LOCATION_MAX = 20
# The highest price a manager can set, $100,000, which keeps the cents inside a Postgres integer.
MAX_PRICE_CENTS = 10_000_000


class AppraisalSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    price_low_cents: int | None
    price_typical_cents: int | None
    price_high_cents: int | None
    confidence: Confidence
    recommendation: Recommendation


class ListingReview(BaseModel):
    channel: Channel
    title: str
    description: str
    category: str
    state: DraftState
    # The checker's flags on the text as it stands, which block approval.
    flags: list[ClaimFlag]
    # The appraisal's typical sale price, which every channel starts from.
    base_price_cents: int | None
    price_override_cents: int | None
    # The price the listing goes up at, the override when there is one.
    price_cents: int | None
    # What a sale at that price leaves after this channel's fees and the supplies.
    net_after_fees_cents: int | None


class ItemReview(BaseModel):
    item_id: UUID
    sku: str
    # The SKU with the box-size suffix, empty until a box is chosen.
    full_sku: str | None
    status: ItemStatus
    release_month: date | None
    category: Category
    brand: str | None
    product: str | None
    condition: Condition
    appraisal: AppraisalSummary | None
    listings: list[ListingReview]
    package_weight_oz: float | None
    # The weight the shipping label is priced by, from the Settings shipping weight rules.
    billed_weight_oz: float | None
    box_code: str | None
    location_code: str | None
    submitted_by_name: str | None
    submitted_at: datetime | None
    # Why the item can't be approved yet, empty when it can or when it isn't waiting for approval.
    blockers: list[str]


class QueueItem(BaseModel):
    item_id: UUID
    sku: str
    full_sku: str | None
    status: ItemStatus
    brand: str | None
    product: str | None
    channels: list[Channel]
    # When staff sent it on, or when a manager approved it for an item waiting for storage.
    waiting_since: datetime | None


class ApprovalQueue(BaseModel):
    # Sent on by staff, oldest first.
    awaiting_approval: list[QueueItem]
    # Approved, or held for its season, with no shelf or bin yet, oldest approval first.
    awaiting_storage: list[QueueItem]


class PriceOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Empty puts the channel back on the appraisal's typical price.
    price_override_cents: Annotated[int, Field(gt=0, le=MAX_PRICE_CENTS)] | None


class StorageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_weight_oz: float
    box_code: Annotated[str, StringConstraints(strip_whitespace=True)]
    # Only once the item is approved, and needed from then on.
    location_code: str | None = None


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class PickListEntry(BaseModel):
    item_id: UUID
    sku: str
    full_sku: str | None
    title: str
    box_code: str | None
    location_code: str | None
    package_weight_oz: float | None


def _locked_item(session: Session, item_id: UUID) -> Item:
    item = session.get(Item, item_id, with_for_update=True)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
    return item


def _card(session: Session, item_id: UUID) -> ItemCard:
    card = session.get(ItemCard, item_id)
    if card is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no card yet.")
    return card


def _base_appraisal(session: Session, item_id: UUID) -> Appraisal | None:
    """The appraisal staff said yes to, whose typical price every channel starts from."""
    latest = latest_decision(session, item_id)
    if latest is None or latest.decision is not DecisionChoice.YES:
        return None
    return session.get(Appraisal, latest.appraisal_id)


def _price_cents(draft: ListingDraft, appraisal: Appraisal | None) -> int | None:
    if draft.price_override_cents is not None:
        return draft.price_override_cents
    return appraisal.price_typical_cents if appraisal else None


def _blockers(
    session: Session, item: Item, card: ItemCard, drafts: list[ListingDraft]
) -> list[str]:
    """Why approval would be refused right now, in the order a manager would fix them."""
    if item.status is not ItemStatus.APPRAISED:
        return []
    latest = latest_decision(session, item.id)
    if latest is None or latest.decision is not DecisionChoice.YES:
        return ["Staff haven't decided to list this item."]
    if not drafts or any(draft.state is not DraftState.AWAITING_APPROVAL for draft in drafts):
        return ["Staff haven't sent this listing for approval yet."]
    blockers: list[str] = []
    facts = ListingFacts.from_card(card)
    appraisal = _base_appraisal(session, item.id)
    for draft in drafts:
        name = CHANNEL_NAMES[draft.channel]
        if check_listing(draft.title, draft.description, facts):
            blockers.append(
                f"{name}'s text makes a claim the item card doesn't support, so reject it and "
                "have staff fix it."
            )
        if _price_cents(draft, appraisal) is None:
            blockers.append(
                f"Set a price for {name}, because the appraisal found no typical sale price."
            )
    needs_package = any(draft.channel is Channel.CHANNEL_A for draft in drafts)
    if needs_package and (item.package_weight_oz is None or item.box_code is None):
        blockers.append(
            "Enter the package weight and box size, which Channel A needs before approval."
        )
    return blockers


def _review(session: Session, item: Item) -> ItemReview:
    card = _card(session, item.id)
    drafts = _item_drafts(session, item.id)
    appraisal = _base_appraisal(session, item.id)
    current = read_store_settings(session)
    facts = ListingFacts.from_card(card)
    listings = []
    for draft in drafts:
        price = _price_cents(draft, appraisal)
        listings.append(
            ListingReview(
                channel=draft.channel,
                title=draft.title,
                description=draft.description,
                category=draft.category,
                state=draft.state,
                flags=check_listing(draft.title, draft.description, facts),
                base_price_cents=appraisal.price_typical_cents if appraisal else None,
                price_override_cents=draft.price_override_cents,
                price_cents=price,
                net_after_fees_cents=(
                    None if price is None else current.net_after_fees_cents(draft.channel, price)
                ),
            )
        )
    submitted = next((draft for draft in drafts if draft.submitted_by is not None), None)
    submitter = session.get(Profile, submitted.submitted_by) if submitted else None
    return ItemReview(
        item_id=item.id,
        sku=item.sku,
        full_sku=item.full_sku,
        status=item.status,
        release_month=item.release_month,
        category=card.category,
        brand=card.brand,
        product=card.product,
        condition=card.condition,
        appraisal=AppraisalSummary.model_validate(appraisal) if appraisal else None,
        listings=listings,
        package_weight_oz=item.package_weight_oz,
        billed_weight_oz=_billed_weight(item, current),
        box_code=item.box_code,
        location_code=item.location_code,
        submitted_by_name=submitter.display_name if submitter else None,
        submitted_at=submitted.submitted_at if submitted else None,
        blockers=_blockers(session, item, card, drafts),
    )


def _billed_weight(item: Item, current: StoreSettings) -> float | None:
    if item.package_weight_oz is None or item.box_code is None:
        return None
    return current.shipping_weight.billed_weight_oz(
        item.package_weight_oz, current.box(item.box_code)
    )


def _queue_item(
    item: Item, card: ItemCard, drafts: list[ListingDraft], since: datetime | None
) -> QueueItem:
    return QueueItem(
        item_id=item.id,
        sku=item.sku,
        full_sku=item.full_sku,
        status=item.status,
        brand=card.brand,
        product=card.product,
        channels=[draft.channel for draft in drafts],
        waiting_since=since,
    )


@router.get("/approvals", operation_id="list_approvals")
def list_approvals(manager: ManagerProfile, session: SessionDep) -> ApprovalQueue:
    """The items waiting for a manager, to approve or to store."""
    rows = session.exec(
        select(Item, ItemCard)
        .join(ItemCard, col(ItemCard.item_id) == col(Item.id))
        .where(col(Item.status).in_([ItemStatus.APPRAISED, *STORABLE]))
        .where(
            sa.exists().where(
                col(ListingDraft.item_id) == col(Item.id),
                col(ListingDraft.state).in_([DraftState.AWAITING_APPROVAL, DraftState.APPROVED]),
            )
        )
    ).all()
    awaiting_approval: list[QueueItem] = []
    awaiting_storage: list[QueueItem] = []
    for item, card in rows:
        drafts = _item_drafts(session, item.id)
        if item.status is ItemStatus.APPRAISED:
            latest = latest_decision(session, item.id)
            waiting = [d for d in drafts if d.state is DraftState.AWAITING_APPROVAL]
            if waiting and latest is not None and latest.decision is DecisionChoice.YES:
                sent = min((d.submitted_at for d in waiting if d.submitted_at), default=None)
                awaiting_approval.append(_queue_item(item, card, waiting, sent))
        elif item.location_code is None:
            approved = [d for d in drafts if d.state is DraftState.APPROVED]
            since = max((d.reviewed_at for d in approved if d.reviewed_at), default=None)
            awaiting_storage.append(_queue_item(item, card, approved, since))
    oldest = datetime.min.replace(tzinfo=UTC)
    for queue in (awaiting_approval, awaiting_storage):
        queue.sort(key=lambda entry: (entry.waiting_since or oldest, entry.sku))
    return ApprovalQueue(awaiting_approval=awaiting_approval, awaiting_storage=awaiting_storage)


@router.get("/items/{item_id}/review", operation_id="get_item_review")
def get_item_review(item_id: UUID, manager: ManagerProfile, session: SessionDep) -> ItemReview:
    return _review(session, _get_item(session, item_id))


@router.put("/items/{item_id}/listings/{channel}/price", operation_id="set_listing_price")
def set_listing_price(
    item_id: UUID,
    channel: Channel,
    override: PriceOverride,
    manager: ManagerProfile,
    session: SessionDep,
) -> ItemReview:
    """Set this channel's price in place of the typical price, or clear it to go back to that."""
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.APPRAISED}, "repriced")
    draft = next((d for d in _item_drafts(session, item_id) if d.channel is channel), None)
    if draft is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"This item has no listing for {CHANNEL_NAMES[channel]}."
        )
    if draft.state is not DraftState.AWAITING_APPROVAL:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a listing waiting for approval can be repriced."
        )
    draft.price_override_cents = override.price_override_cents
    session.add(draft)
    session.commit()
    return _review(session, item)


def _location(code: str | None) -> str | None:
    if code is None:
        return None
    # Spaces run together and close up around a dash, so "b12 - 2" is saved as B12-2.
    cleaned = re.sub(r" ?- ?", "-", " ".join(code.split())).upper()
    if not cleaned:
        return None
    if len(cleaned) > LOCATION_MAX or not LOCATION_PATTERN.match(cleaned):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Write the shelf or bin code in at most {LOCATION_MAX} letters, numbers, spaces and "
            "dashes, such as A3 or B12-2.",
        )
    return cleaned


@router.put("/items/{item_id}/storage", operation_id="save_item_storage")
def save_item_storage(
    item_id: UUID, request: StorageRequest, manager: ManagerProfile, session: SessionDep
) -> ItemReview:
    """Save the package, before or after approval, and the shelf or bin once it is approved."""
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.APPRAISED, *STORABLE}, "stored")
    location = _location(request.location_code)
    if item.status is ItemStatus.APPRAISED:
        drafts = _item_drafts(session, item_id)
        if not any(draft.state is DraftState.AWAITING_APPROVAL for draft in drafts):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Staff haven't sent this listing for approval yet."
            )
        if location is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Add the shelf or bin code once the item is approved."
            )
    elif location is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the shelf or bin code.")
    current = read_store_settings(session)
    try:
        current.shipping_weight.check_weight(request.package_weight_oz)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    if current.box(request.box_code) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose one of the box sizes in Settings."
        )
    item.package_weight_oz = request.package_weight_oz
    item.box_code = request.box_code
    item.location_code = location
    session.add(item)
    session.commit()
    return _review(session, item)


def _approved_status(item: Item, today: date) -> ItemStatus:
    """Held for its season while its release month is still to come, and approved otherwise."""
    if item.release_month is not None and item.release_month > today.replace(day=1):
        return ItemStatus.HELD_FOR_SEASON
    return ItemStatus.APPROVED


@router.post("/items/{item_id}/approve", operation_id="approve_item")
def approve_item(item_id: UUID, manager: ManagerProfile, session: SessionDep) -> ItemReview:
    """Approve every listing staff sent on, once each has a price and Channel A has a package."""
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.APPRAISED}, "approved")
    card = _card(session, item_id)
    drafts = _item_drafts(session, item_id)
    blockers = _blockers(session, item, card, drafts)
    if blockers:
        raise HTTPException(status.HTTP_409_CONFLICT, " ".join(blockers))
    now = datetime.now(UTC)
    for draft in drafts:
        draft.state = DraftState.APPROVED
        draft.reviewed_by = manager.auth_user_id
        draft.reviewed_at = now
        session.add(draft)
    # The release month stays as it is, so a held item is released when its season comes.
    item.status = _approved_status(item, now.date())
    session.add(item)
    session.commit()
    return _review(session, item)


@router.post("/items/{item_id}/reject", operation_id="reject_item")
def reject_item(
    item_id: UUID, request: RejectRequest, manager: ManagerProfile, session: SessionDep
) -> ItemReview:
    """Turn the item down, which records a manager's no and needs no package or shelf."""
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.APPRAISED}, "rejected")
    drafts = _item_drafts(session, item_id)
    latest = latest_decision(session, item_id)
    waiting = [draft for draft in drafts if draft.state is DraftState.AWAITING_APPROVAL]
    if not waiting or latest is None or latest.decision is not DecisionChoice.YES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Staff haven't sent this listing for approval yet."
        )
    now = datetime.now(UTC)
    for draft in waiting:
        draft.state = DraftState.REJECTED
        draft.reviewed_by = manager.auth_user_id
        draft.reviewed_at = now
        session.add(draft)
    session.add(
        Decision(
            item_id=item_id,
            appraisal_id=latest.appraisal_id,
            decision=DecisionChoice.NO,
            override_reason=request.reason,
            note=request.note or None,
            decided_by=manager.auth_user_id,
            decided_at=now,
        )
    )
    item.status = ItemStatus.DECLINED
    session.add(item)
    session.commit()
    return _review(session, item)


def mark_sold(session: Session, item_id: UUID) -> Item:
    """Record that a listed item sold, which puts it on the pick list.

    This is the call the channel sync in #21 makes when a sale arrives. The caller commits.
    """
    item = session.get(Item, item_id, with_for_update=True)
    if item is None:
        raise LookupError(f"Item {item_id} doesn't exist.")
    if item.status is not ItemStatus.LISTED:
        raise ValueError(f"An item that is {item.status.value} can't be sold.")
    item.status = ItemStatus.SOLD
    session.add(item)
    return item


def _natural(text: str) -> list[tuple[int, int | str]]:
    """A2 before A10: digits compare as numbers and letters as text."""
    return [(0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", text)]


def pick_order(entries: list[PickListEntry], current: StoreSettings) -> list[PickListEntry]:
    """By box section, in the order the Settings list has the boxes, then by shelf or bin."""
    codes = [box.code for box in current.box_sizes.boxes]

    def key(entry: PickListEntry) -> tuple[object, ...]:
        box = entry.box_code
        # A box no longer in Settings comes after the listed ones, and no box comes last.
        if box in codes:
            section = (codes.index(box), "")
        else:
            section = (len(codes) + (box is None), box or "")
        shelf = (entry.location_code is None, _natural(entry.location_code or ""))
        return (section, shelf, entry.sku)

    return sorted(entries, key=key)


@router.get("/pick-list", operation_id="get_pick_list")
def get_pick_list(profile: CurrentProfile, session: SessionDep) -> list[PickListEntry]:
    """Every sold item still to pick, in the order to walk the shelves."""
    rows = session.exec(
        select(Item, ItemCard)
        .join(ItemCard, col(ItemCard.item_id) == col(Item.id))
        .where(Item.status == ItemStatus.SOLD)
    ).all()
    entries = []
    for item, card in rows:
        drafts = _item_drafts(session, item.id)
        title = drafts[0].title if drafts else " ".join(filter(None, [card.brand, card.product]))
        entries.append(
            PickListEntry(
                item_id=item.id,
                sku=item.sku,
                full_sku=item.full_sku,
                title=title or item.sku,
                box_code=item.box_code,
                location_code=item.location_code,
                package_weight_oz=item.package_weight_oz,
            )
        )
    return pick_order(entries, read_store_settings(session))


@router.post(
    "/items/{item_id}/picked",
    operation_id="mark_item_picked",
    status_code=status.HTTP_204_NO_CONTENT,
)
def mark_item_picked(item_id: UUID, profile: CurrentProfile, session: SessionDep) -> None:
    """Take a sold item off the pick list once it is off the shelf."""
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.SOLD}, "picked")
    item.status = ItemStatus.PICKED
    session.add(item)
    session.commit()
