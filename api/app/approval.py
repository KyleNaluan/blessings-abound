"""The manager's step after drafting, the storage step after approval, and the pick list.

A manager reviews the listing drafts staff sent on, may set a price per channel in place of the
appraisal's typical price, and approves or rejects the item. Channel A needs the package weight and
box size before approval, and every approved item gets them and a shelf or bin code when stored.
Storing an approved item publishes its approved listings to the sales channels, through the jobs
that app/sync.py runs, and a sale on a channel calls `mark_sold`, which puts it on the pick list.
A sold item is on the pick list until someone picks it.

An item held for its season comes back to the queue in its release month, worked out on every read,
and waits for a manager to check its price against fresh comps before it is listed. A manager can
also send it back early, or take an item out of online selling and later put it back for review,
and each of those choices is kept in `decisions` with the staff yes and no, which is the item's
history.
"""

import re
from collections.abc import Collection
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.dialects.postgresql import ARRAY, distinct_on
from sqlalchemy.orm import Mapped
from sqlmodel import Session, col, select

from app.appraisal import (
    AppraisalRead,
    _get_item,  # pyright: ignore[reportPrivateUsage]
    _item_drafts,  # pyright: ignore[reportPrivateUsage]
    _require_status,  # pyright: ignore[reportPrivateUsage]
    get_ebay_search,
    latest_decision,
)
from app.auth import CurrentProfile, ManagerProfile
from app.channel_timing import get_today
from app.channels import ChannelsDep, ListingContent
from app.claims import ClaimFlag, ListingFacts, check_listing
from app.comps import EbaySearch
from app.db import get_session
from app.jobs import publish_item
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
    Listing,
    ListingDraft,
    ListingStatus,
    Profile,
    Recommendation,
    Role,
)
from app.pipeline import price_item
from app.store_settings import StoreSettings, read_store_settings

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
# Today in UTC, which the release month of a held item is read against.
TodayDep = Annotated[date, Depends(get_today)]

# The statuses of an approved item that is not yet published, which the storage step works on.
STORABLE = {ItemStatus.APPROVED, ItemStatus.HELD_FOR_SEASON}
LOCATION_PATTERN = re.compile(r"^[A-Z0-9]+(?:[ -][A-Z0-9]+)*$")
LOCATION_MAX = 20
# The highest price a manager can set, $100,000, which keeps the cents inside a Postgres integer.
MAX_PRICE_CENTS = 10_000_000
NOTE_MAX = 200
# The words a manager's choices are kept under in `decisions`, beside the staff reasons.
NOT_LISTED_ONLINE = "Not listed online"
PUT_BACK = "Put back for review"
# The most items the Not listed online list shows, newest first.
NOT_ONLINE_LIST_MAX = 50


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
    # Where the listing is on the channel, empty until the stored item is published there.
    channel_status: ListingStatus | None
    # Why the channel refused the listing or the publish gave up.
    channel_detail: str | None


class HistoryEntry(BaseModel):
    decision: DecisionChoice
    # One of the staff reasons from the appraisal screen, or a manager's own words.
    reason: str | None
    note: str | None
    decided_by_name: str
    decided_at: datetime


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
    # Who last approved the listings and when, empty until a manager has.
    approved_by_name: str | None
    approved_at: datetime | None
    # Held for its season and back for a manager to check before it is listed, because its release
    # month has come or a manager sent it back early.
    back_for_review: bool
    # Kept off online and then put back for review by a manager, until it is approved or rejected.
    put_back: bool
    # The comps looked up again since the approval, for an item back for review, empty until then.
    fresh_appraisal: AppraisalRead | None
    # Every yes and no on the item, oldest first, from staff and managers.
    history: list[HistoryEntry]
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
    # When staff sent it on, when a manager approved it for an item waiting for storage, or the
    # start of its release month for a held item back for review.
    waiting_since: datetime | None
    release_month: date | None
    location_code: str | None
    back_for_review: bool
    put_back: bool


class KeptOffItem(BaseModel):
    """An item that is not listed online, with who kept it off, when and why."""

    item_id: UUID
    sku: str
    brand: str | None
    product: str | None
    note: str | None
    decided_by_name: str
    decided_at: datetime


class KeptOffMatch(KeptOffItem):
    """An earlier item kept off online that a new item may be, by its photo or its card."""

    matched_on: Literal["photo", "brand_and_product"]


class ApprovalQueue(BaseModel):
    # Sent on by staff, and held items back for review, oldest first.
    awaiting_approval: list[QueueItem]
    # Approved, or held for its season, with no shelf or bin yet, oldest approval first.
    awaiting_storage: list[QueueItem]
    # Held for its season with its release month still to come, soonest release first.
    held_for_season: list[QueueItem]
    # Kept off online, newest first, which a manager can put back for review.
    not_listed_online: list[KeptOffItem]


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


class NotOnlineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_MAX)
    ]


class PutBackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_MAX)
    ]


class NotOnlineResult(BaseModel):
    item_id: UUID
    status: ItemStatus
    note: str
    decided_by_name: str
    decided_at: datetime


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


def month_name(month: date) -> str:
    return month.strftime("%B %Y")


def back_for_review(item: Item, today: date) -> bool:
    """Held for its season with its release month come, so it waits for a manager to list it."""
    if item.status is not ItemStatus.HELD_FOR_SEASON:
        return False
    return item.release_month is None or item.release_month <= today.replace(day=1)


def _approved_drafts(drafts: list[ListingDraft]) -> list[ListingDraft]:
    return [draft for draft in drafts if draft.state is DraftState.APPROVED]


def _approval_time(drafts: list[ListingDraft]) -> datetime | None:
    return max((d.reviewed_at for d in _approved_drafts(drafts) if d.reviewed_at), default=None)


def _decide(
    session: Session, item: Item, choice: DecisionChoice, reason: str, by: Profile, note: str | None
) -> Decision:
    """Add a manager's or staff member's choice to the item's history. The caller commits.

    It points at the appraisal the standing yes was made on, so the listing keeps its typical
    price, and is stamped here rather than by now(), so the newest choice is the one that stands.
    """
    latest = latest_decision(session, item.id)
    if latest is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Staff haven't decided to list this item.")
    decision = Decision(
        item_id=item.id,
        appraisal_id=latest.appraisal_id,
        decision=choice,
        override_reason=reason,
        note=note,
        decided_by=by.auth_user_id,
        decided_at=datetime.now(UTC),
    )
    session.add(decision)
    return decision


def _history(session: Session, item_id: UUID) -> list[HistoryEntry]:
    rows = session.exec(
        select(Decision, Profile.display_name)
        .join(Profile, col(Profile.auth_user_id) == col(Decision.decided_by))
        .where(Decision.item_id == item_id)
        .order_by(col(Decision.decided_at), col(Decision.id))
    ).all()
    return [
        HistoryEntry(
            decision=decision.decision,
            reason=decision.override_reason,
            note=decision.note,
            decided_by_name=name,
            decided_at=decision.decided_at,
        )
        for decision, name in rows
    ]


def is_put_back(item: Item, latest: Decision | None) -> bool:
    """Kept off online and put back for review, and not yet approved or rejected since."""
    return (
        item.status in {ItemStatus.APPRAISED, ItemStatus.HELD_FOR_SEASON}
        and latest is not None
        and latest.override_reason == PUT_BACK
    )


def _fresh_appraisal(
    session: Session, item_id: UUID, drafts: list[ListingDraft]
) -> Appraisal | None:
    """The newest appraisal since the listings were approved, which is a fresh look at comps.

    For an item put back for review, it has to be newer than that too, because it may have been
    kept off online for months after an earlier lookup.
    """
    since = _approval_time(drafts)
    if since is None:
        return None
    latest = latest_decision(session, item_id)
    if latest is not None and latest.override_reason == PUT_BACK:
        since = max(since, latest.decided_at)
    return session.exec(
        select(Appraisal)
        .where(Appraisal.item_id == item_id, col(Appraisal.created_at) > since)
        .order_by(col(Appraisal.created_at).desc())
        .limit(1)
    ).first()


def _blockers(
    session: Session, item: Item, card: ItemCard, drafts: list[ListingDraft], today: date
) -> list[str]:
    """Why approval would be refused right now, in the order a manager would fix them."""
    if item.status is ItemStatus.APPRAISED:
        latest = latest_decision(session, item.id)
        if latest is None or latest.decision is not DecisionChoice.YES:
            return ["Staff haven't decided to list this item."]
        if not drafts or any(draft.state is not DraftState.AWAITING_APPROVAL for draft in drafts):
            return ["Staff haven't sent this listing for approval yet."]
    elif not back_for_review(item, today):
        return []
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


def _review(session: Session, item: Item, today: date) -> ItemReview:
    card = _card(session, item.id)
    drafts = _item_drafts(session, item.id)
    appraisal = _base_appraisal(session, item.id)
    current = read_store_settings(session)
    facts = ListingFacts.from_card(card)
    published = {
        listing.channel: listing
        for listing in session.exec(select(Listing).where(Listing.item_id == item.id))
    }
    listings = []
    for draft in drafts:
        price = _price_cents(draft, appraisal)
        on_channel = published.get(draft.channel)
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
                channel_status=on_channel.status if on_channel else None,
                channel_detail=on_channel.status_detail if on_channel else None,
            )
        )
    submitted = next((draft for draft in drafts if draft.submitted_by is not None), None)
    submitter = session.get(Profile, submitted.submitted_by) if submitted else None
    approved_at = _approval_time(drafts)
    reviewed = next((d for d in _approved_drafts(drafts) if d.reviewed_at == approved_at), None)
    approver = (
        session.get(Profile, reviewed.reviewed_by) if reviewed and reviewed.reviewed_by else None
    )
    reviewing = back_for_review(item, today)
    fresh = _fresh_appraisal(session, item.id, drafts) if reviewing else None
    latest = latest_decision(session, item.id)
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
        approved_by_name=approver.display_name if approver else None,
        approved_at=approved_at,
        back_for_review=reviewing,
        put_back=is_put_back(item, latest),
        fresh_appraisal=AppraisalRead.model_validate(fresh) if fresh else None,
        history=_history(session, item.id),
        blockers=_blockers(session, item, card, drafts, today),
    )


def _billed_weight(item: Item, current: StoreSettings) -> float | None:
    if item.package_weight_oz is None or item.box_code is None:
        return None
    return current.shipping_weight.billed_weight_oz(
        item.package_weight_oz, current.box(item.box_code)
    )


def _queue_item(
    item: Item,
    card: ItemCard,
    drafts: list[ListingDraft],
    since: datetime | None,
    today: date,
    put_back: bool = False,
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
        release_month=item.release_month,
        location_code=item.location_code,
        back_for_review=back_for_review(item, today),
        put_back=put_back,
    )


def _latest_decisions():
    """Each item's newest decision, the one that stands, as a subquery."""
    return (
        sa.select(
            col(Decision.item_id),
            col(Decision.note),
            col(Decision.decided_by),
            col(Decision.decided_at),
        )
        .ext(distinct_on(col(Decision.item_id)))
        .order_by(col(Decision.item_id), col(Decision.decided_at).desc(), col(Decision.id))
        .subquery()
    )


def _kept_off_query():
    """The items not listed online with who kept them off, when and why, newest first."""
    latest = _latest_decisions()
    return (
        sa.select(
            col(Item.id).label("item_id"),
            col(Item.sku),
            col(Item.photo_hashes),
            col(ItemCard.brand),
            col(ItemCard.product),
            latest.c.note,
            col(Profile.display_name).label("decided_by_name"),
            latest.c.decided_at,
        )
        .join(latest, latest.c.item_id == col(Item.id))
        .join(Profile, col(Profile.auth_user_id) == latest.c.decided_by)
        .outerjoin(ItemCard, col(ItemCard.item_id) == col(Item.id))
        .where(col(Item.status) == ItemStatus.NOT_LISTED_ONLINE)
        .order_by(latest.c.decided_at.desc(), col(Item.id))
    )


def _same_text(column: Mapped[str | None], value: str) -> sa.ColumnElement[bool]:
    return sa.func.lower(sa.func.btrim(column)) == value.strip().lower()


def _month_start(month: date | None) -> datetime | None:
    return datetime(month.year, month.month, 1, tzinfo=UTC) if month else None


@router.get("/approvals", operation_id="list_approvals")
def list_approvals(manager: ManagerProfile, session: SessionDep, today: TodayDep) -> ApprovalQueue:
    """The items waiting for a manager, to approve, to store, or held for their season.

    A held item comes back to approval once its release month has come, which is read here
    against today rather than moved by a scheduled job, so it shows the first time anyone looks.
    """
    rows = session.exec(
        select(Item, ItemCard)
        .join(ItemCard, col(ItemCard.item_id) == col(Item.id))
        .where(col(Item.status).in_([ItemStatus.APPRAISED, *STORABLE]))
        .where(
            sa.or_(
                sa.exists().where(
                    col(ListingDraft.item_id) == col(Item.id),
                    col(ListingDraft.state).in_(
                        [DraftState.AWAITING_APPROVAL, DraftState.APPROVED]
                    ),
                ),
                # Put back for review with no listing sent yet, which the manager writes.
                sa.exists().where(
                    col(Decision.item_id) == col(Item.id), col(Decision.override_reason) == PUT_BACK
                ),
            )
        )
    ).all()
    awaiting_approval: list[QueueItem] = []
    awaiting_storage: list[QueueItem] = []
    held: list[QueueItem] = []
    for item, card in rows:
        drafts = _item_drafts(session, item.id)
        latest = latest_decision(session, item.id)
        put_back = is_put_back(item, latest)
        if item.status is ItemStatus.APPRAISED:
            waiting = [d for d in drafts if d.state is DraftState.AWAITING_APPROVAL]
            if latest is None or latest.decision is not DecisionChoice.YES:
                continue
            if put_back:
                assert latest is not None
                entry = _queue_item(item, card, waiting, latest.decided_at, today, put_back=True)
                awaiting_approval.append(entry)
            elif waiting:
                sent = min((d.submitted_at for d in waiting if d.submitted_at), default=None)
                awaiting_approval.append(_queue_item(item, card, waiting, sent, today))
            continue
        approved = _approved_drafts(drafts)
        if back_for_review(item, today):
            since = latest.decided_at if put_back and latest else _month_start(item.release_month)
            entry = _queue_item(item, card, approved, since, today, put_back=put_back)
            awaiting_approval.append(entry)
            continue
        entry = _queue_item(item, card, approved, _approval_time(drafts), today)
        if item.location_code is None:
            awaiting_storage.append(entry)
        if item.status is ItemStatus.HELD_FOR_SEASON:
            held.append(entry)
    oldest = datetime.min.replace(tzinfo=UTC)
    for queue in (awaiting_approval, awaiting_storage):
        queue.sort(key=lambda entry: (entry.waiting_since or oldest, entry.sku))
    held.sort(key=lambda entry: (entry.release_month or date.min, entry.sku))
    kept_off = session.connection().execute(_kept_off_query().limit(NOT_ONLINE_LIST_MAX))
    return ApprovalQueue(
        awaiting_approval=awaiting_approval,
        awaiting_storage=awaiting_storage,
        held_for_season=held,
        not_listed_online=[KeptOffItem.model_validate(dict(row)) for row in kept_off.mappings()],
    )


@router.get("/items/{item_id}/review", operation_id="get_item_review")
def get_item_review(
    item_id: UUID, manager: ManagerProfile, session: SessionDep, today: TodayDep
) -> ItemReview:
    return _review(session, _get_item(session, item_id), today)


@router.put("/items/{item_id}/listings/{channel}/price", operation_id="set_listing_price")
def set_listing_price(
    item_id: UUID,
    channel: Channel,
    override: PriceOverride,
    manager: ManagerProfile,
    session: SessionDep,
    today: TodayDep,
) -> ItemReview:
    """Set this channel's price in place of the typical price, or clear it to go back to that.

    A held item back for review can be repriced too, before a manager approves it again.
    """
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.APPRAISED, ItemStatus.HELD_FOR_SEASON}, "repriced")
    reviewing = back_for_review(item, today)
    if item.status is ItemStatus.HELD_FOR_SEASON and not reviewing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A held item can be repriced once it's back for review, so choose List now first.",
        )
    draft = next((d for d in _item_drafts(session, item_id) if d.channel is channel), None)
    if draft is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"This item has no listing for {CHANNEL_NAMES[channel]}."
        )
    waiting = DraftState.APPROVED if reviewing else DraftState.AWAITING_APPROVAL
    if draft.state is not waiting:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a listing waiting for approval can be repriced."
        )
    draft.price_override_cents = override.price_override_cents
    session.add(draft)
    session.commit()
    return _review(session, item, today)


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
    item_id: UUID,
    request: StorageRequest,
    manager: ManagerProfile,
    session: SessionDep,
    channels: ChannelsDep,
    today: TodayDep,
) -> ItemReview:
    """Save the package, before or after approval, and the shelf or bin once it is approved.

    An approved item is queued to be published on the channels set up on this server once it has
    its shelf or bin, and the scheduler in app/scheduler.py runs the jobs within seconds. One held
    for its season waits.
    """
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
    if item.status is ItemStatus.APPROVED:
        publish_approved(session, item, channels)
    session.commit()
    return _review(session, item, today)


def listing_content(card: ItemCard, draft: ListingDraft, price_cents: int) -> ListingContent:
    """What one channel shows: the text a manager approved, at the manager's price."""
    details = {
        "department": card.department.value if card.department else None,
        "size_type": card.size_type,
        "material": card.material,
        "model": card.exact_model,
        "platform": card.platform,
        "accessories": card.accessories_included,
    }
    return ListingContent(
        title=draft.title,
        description=draft.description,
        category=draft.category,
        condition=card.condition.value,
        price_cents=price_cents,
        brand=card.brand,
        size=card.size,
        color=card.color,
        specifics={key: value for key, value in details.items() if value},
    )


def publish_approved(session: Session, item: Item, channels: Collection[Channel]) -> list[UUID]:
    """Queue each approved listing of a stored item for its channel, and return the jobs to run.

    Only the given channels, the ones set up on this server, are published to, so no job waits
    for a channel nothing will run it for. It is safe to call again, because a channel the item
    is already on is left alone and only a refused or failed listing is sent again. The caller
    commits.
    """
    if item.status not in (ItemStatus.APPROVED, ItemStatus.LISTED) or item.location_code is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only an approved item with a shelf or bin can be published."
        )
    card = _card(session, item.id)
    appraisal = _base_appraisal(session, item.id)
    drafts = [d for d in _item_drafts(session, item.id) if d.state is DraftState.APPROVED]
    contents: dict[Channel, ListingContent] = {}
    for draft in (d for d in drafts if d.channel in channels):
        price = _price_cents(draft, appraisal)
        # Approval refuses a listing with no price, so this only guards against a later change.
        if price is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{CHANNEL_NAMES[draft.channel]} has no price."
            )
        contents[draft.channel] = listing_content(card, draft, price)
    # The database holds an approved listing to the manager who approved it and when.
    reviewed = next((d for d in drafts if d.reviewed_by and d.reviewed_at), None)
    if reviewed is None or reviewed.reviewed_by is None or reviewed.reviewed_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No listing of this item is approved.")
    return publish_item(session, item.id, contents, reviewed.reviewed_by, reviewed.reviewed_at)


def _approved_status(item: Item, today: date) -> ItemStatus:
    """Held for its season while its release month is still to come, and approved otherwise."""
    if item.release_month is not None and item.release_month > today.replace(day=1):
        return ItemStatus.HELD_FOR_SEASON
    return ItemStatus.APPROVED


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _prices(session: Session, item: Item, drafts: list[ListingDraft]) -> str:
    """Each channel's price in words, such as "$45.00 on Channel A and $40.00 on Channel B"."""
    appraisal = _base_appraisal(session, item.id)
    prices = []
    for draft in drafts:
        price = _price_cents(draft, appraisal)
        if price is not None:
            prices.append(f"{_money(price)} on {CHANNEL_NAMES[draft.channel]}")
    return " and ".join(prices)


@router.post("/items/{item_id}/approve", operation_id="approve_item")
def approve_item(
    item_id: UUID,
    manager: ManagerProfile,
    session: SessionDep,
    channels: ChannelsDep,
    today: TodayDep,
) -> ItemReview:
    """Approve every listing staff sent on, once each has a price and Channel A has a package.

    A held item back for review is approved again at the prices on the review, which lists it
    straight away when it is already on a shelf, the same way storing an approved item does.
    """
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.APPRAISED, ItemStatus.HELD_FOR_SEASON}, "approved")
    if item.status is ItemStatus.HELD_FOR_SEASON and not back_for_review(item, today):
        assert item.release_month is not None
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This item is held until {month_name(item.release_month)}, so choose List now to "
            "review it before then.",
        )
    card = _card(session, item_id)
    drafts = _item_drafts(session, item_id)
    blockers = _blockers(session, item, card, drafts, today)
    if blockers:
        raise HTTPException(status.HTTP_409_CONFLICT, " ".join(blockers))
    again = item.status is ItemStatus.HELD_FOR_SEASON
    now = datetime.now(UTC)
    for draft in drafts:
        draft.state = DraftState.APPROVED
        draft.reviewed_by = manager.auth_user_id
        draft.reviewed_at = now
        session.add(draft)
    # The release month stays as it is, so a held item comes back for review when its season comes.
    item.status = ItemStatus.APPROVED if again else _approved_status(item, today)
    session.add(item)
    if again:
        reason = f"Approved again in its season at {_prices(session, item, drafts)}"
        _decide(session, item, DecisionChoice.YES, reason, manager, None)
        if item.location_code is not None:
            publish_approved(session, item, channels)
    elif item.status is ItemStatus.HELD_FOR_SEASON:
        assert item.release_month is not None
        reason = f"Approved and held for its season until {month_name(item.release_month)}"
        _decide(session, item, DecisionChoice.YES, reason, manager, None)
    session.commit()
    return _review(session, item, today)


@router.post("/items/{item_id}/reject", operation_id="reject_item")
def reject_item(
    item_id: UUID,
    request: RejectRequest,
    manager: ManagerProfile,
    session: SessionDep,
    today: TodayDep,
) -> ItemReview:
    """Turn the item down, which records a manager's no and needs no package or shelf.

    A held item back for review can be turned down the same way, instead of being approved again.
    """
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.APPRAISED, ItemStatus.HELD_FOR_SEASON}, "rejected")
    reviewing = back_for_review(item, today)
    if item.status is ItemStatus.HELD_FOR_SEASON and not reviewing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A held item can be rejected once it's back for review, so choose List now first.",
        )
    drafts = _item_drafts(session, item_id)
    latest = latest_decision(session, item_id)
    waiting_state = DraftState.APPROVED if reviewing else DraftState.AWAITING_APPROVAL
    waiting = [draft for draft in drafts if draft.state is waiting_state]
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
    return _review(session, item, today)


@router.post("/items/{item_id}/list-now", operation_id="list_held_item_now")
def list_held_item_now(
    item_id: UUID, manager: ManagerProfile, session: SessionDep, today: TodayDep
) -> ItemReview:
    """Bring a held item back for review before its release month, with the same price check.

    Its release month becomes this month, so it is back for review exactly as it would be in its
    season, and the month it was held until is kept in the history. Asking again changes nothing.
    """
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.HELD_FOR_SEASON}, "listed now")
    if not back_for_review(item, today):
        assert item.release_month is not None
        reason = f"Sent for review before its release month of {month_name(item.release_month)}"
        _decide(session, item, DecisionChoice.YES, reason, manager, None)
        item.release_month = today.replace(day=1)
        session.add(item)
        session.commit()
    return _review(session, item, today)


@router.post("/items/{item_id}/not-online", operation_id="keep_item_off_online")
def keep_item_off_online(
    item_id: UUID, request: NotOnlineRequest, profile: CurrentProfile, session: SessionDep
) -> NotOnlineResult:
    """Take the item out of online selling, such as to sell it on the store floor.

    Staff can do it from the item screen before a manager approves the listing, and a manager can
    also do it to an item held for its season. Who did it, when and the note go in the history,
    and only a manager can put it back for review afterwards.
    """
    item = _locked_item(session, item_id)
    _require_status(
        item, {ItemStatus.APPRAISED, ItemStatus.HELD_FOR_SEASON}, "taken out of online selling"
    )
    if item.status is ItemStatus.HELD_FOR_SEASON and profile.role != Role.MANAGER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a manager can do this.")
    latest = latest_decision(session, item_id)
    if latest is None or latest.decision is not DecisionChoice.YES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Staff haven't decided to list this item.")
    decision = _decide(session, item, DecisionChoice.NO, NOT_LISTED_ONLINE, profile, request.note)
    item.status = ItemStatus.NOT_LISTED_ONLINE
    session.add(item)
    session.commit()
    return NotOnlineResult(
        item_id=item.id,
        status=item.status,
        note=request.note,
        decided_by_name=profile.display_name,
        decided_at=decision.decided_at,
    )


@router.post("/items/{item_id}/put-back", operation_id="put_item_back_for_review")
def put_item_back_for_review(
    item_id: UUID,
    request: PutBackRequest,
    manager: ManagerProfile,
    session: SessionDep,
    today: TodayDep,
) -> ItemReview:
    """Undo Don't list online, right after or any time later, with a note on why.

    The item goes back to Waiting for approval, so nothing is listed until a manager reviews it
    again. One that was approved before comes back like a held item in its season, with its comps
    looked up again, and one that wasn't goes back to its listings waiting for approval, or to
    being written when staff never sent one.
    """
    item = _locked_item(session, item_id)
    _require_status(item, {ItemStatus.NOT_LISTED_ONLINE}, "put back for review")
    _decide(session, item, DecisionChoice.YES, PUT_BACK, manager, request.note)
    if _approved_drafts(_item_drafts(session, item_id)):
        item.status = ItemStatus.HELD_FOR_SEASON
        item.release_month = today.replace(day=1)
    else:
        item.status = ItemStatus.APPRAISED
    session.add(item)
    session.commit()
    return _review(session, item, today)


@router.get("/items/{item_id}/kept-off-matches", operation_id="list_kept_off_matches")
def list_kept_off_matches(
    item_id: UUID, profile: CurrentProfile, session: SessionDep
) -> list[KeptOffMatch]:
    """Earlier items kept off online that this one may be, newest first, for a warning at intake.

    An item matches on a shared photo, or on the same brand and product once the card is read,
    ignoring case and spaces at the ends, because a new photo of the same item won't match. One
    that was put back for review is no longer kept off, so it doesn't match.
    """
    item = _get_item(session, item_id)
    card = session.get(ItemCard, item_id)
    same_photo = col(Item.photo_hashes).op("&&")(sa.literal(item.photo_hashes, ARRAY(sa.Text)))
    conditions: list[sa.ColumnElement[bool]] = [same_photo] if item.photo_hashes else []
    brand = (card.brand or "").strip() if card else ""
    product = (card.product or "").strip() if card else ""
    if brand and product:
        conditions.append(
            sa.and_(
                _same_text(col(ItemCard.brand), brand), _same_text(col(ItemCard.product), product)
            )
        )
    if not conditions:
        return []
    rows = session.connection().execute(
        _kept_off_query().where(col(Item.id) != item_id).where(sa.or_(*conditions))
    )
    hashes = set(item.photo_hashes)
    return [
        KeptOffMatch.model_validate(
            dict(row)
            | {"matched_on": "photo" if hashes & set(row.photo_hashes) else "brand_and_product"}
        )
        for row in rows.mappings()
    ]


@router.post("/items/{item_id}/fresh-comps", operation_id="look_up_fresh_comps")
def look_up_fresh_comps(
    item_id: UUID,
    manager: ManagerProfile,
    session: SessionDep,
    search: Annotated[EbaySearch | None, Depends(get_ebay_search)],
    today: TodayDep,
) -> ItemReview:
    """Look up comps again for a held item back for review, so its price is checked before listing.

    It runs the appraisal's own lookup and pricing and keeps the result as a new appraisal of the
    item, which the listings don't take their typical price from. Once there is one since the
    approval, asking again returns it rather than searching again.
    """
    item = _get_item(session, item_id)
    if not back_for_review(item, today):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a held item back for review has its comps looked up."
        )
    if _fresh_appraisal(session, item_id, _item_drafts(session, item_id)) is None:
        result = price_item(_card(session, item_id), session, search)
        # The search lets go of the database, so the item may have moved on while it ran.
        item = session.get(Item, item_id, with_for_update=True, populate_existing=True)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
        if not back_for_review(item, today):
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This item was approved or turned down meanwhile."
            )
        if _fresh_appraisal(session, item_id, _item_drafts(session, item_id)) is None:
            # Stamped here rather than by now(), so it reads as newer than the approval.
            session.add(
                Appraisal(item_id=item_id, created_at=datetime.now(UTC), **result.model_dump())
            )
        session.commit()
    return _review(session, item, today)


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
