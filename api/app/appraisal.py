"""The staff path from a photo to a saved decision, one route per step."""

import logging
from datetime import UTC, date, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid4

import httpx2
import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)
from sqlmodel import Session, col, select

from app.ai import AINotConfiguredError, ChatModel, get_chat_model, get_fallback_chat_model
from app.auth import CurrentProfile
from app.channel_timing import ChannelRecommendation, advise, get_today, recommend
from app.claims import ClaimFlag, ListingFacts, check_listing
from app.comps import EbaySearch, serpapi_ebay_search
from app.db import get_session
from app.intake import (
    MAX_PHOTO_BYTES,
    CheckedPhoto,
    PhotoError,
    RejectedMatch,
    check_photo,
    get_now,
    initials,
    next_sku,
    rejected_matches,
    sku_prefix,
    store_date,
)
from app.listing_drafts import (
    CHANNEL_NAMES,
    DESCRIPTION_MAX,
    TITLE_MAX,
    category_options,
)
from app.models import (
    MAX_PHOTOS,
    Appraisal,
    Category,
    Channel,
    Condition,
    Confidence,
    Decision,
    DecisionChoice,
    Department,
    Destination,
    DraftSource,
    DraftState,
    FallbackReason,
    Flaw,
    Item,
    ItemCard,
    ItemStatus,
    ListingDraft,
    Profile,
    Recommendation,
    Role,
    StoreDepartment,
    TriageEntry,
    TriageOutcome,
)
from app.pipeline import (
    PricedComp,
    draft_item_card,
    draft_listing,
    needs_confirmation,
    photo_retake_reason,
    price_item,
)
from app.settings import get_settings
from app.storage import PhotoTooLargeError, Storage, get_storage
from app.store_settings import read_store_settings
from app.vision import ItemCardError, UnreadablePhotoError

logger = logging.getLogger(__name__)

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache
def get_photo_storage() -> Storage:
    return get_storage()


@lru_cache
def _configured_vision_providers() -> tuple[ChatModel, ...]:
    fallback = get_fallback_chat_model()
    return (get_chat_model(), fallback) if fallback else (get_chat_model(),)


def get_vision_providers() -> list[ChatModel]:
    """The providers in order, or none when the model is not set up."""
    try:
        return list(_configured_vision_providers())
    except AINotConfiguredError as error:
        logger.warning("%s", error)
        return []


def get_draft_providers() -> list[ChatModel]:
    """The same providers as the item card, which write the listing drafts."""
    return get_vision_providers()


def get_reason_providers() -> list[ChatModel]:
    """The same providers again, which word the reason for the channel recommendation."""
    return get_vision_providers()


def get_ebay_search() -> EbaySearch | None:
    """The SerpApi search, or none when the key is not set."""
    key = get_settings().serpapi_api_key
    return serpapi_ebay_search(key) if key else None


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip() or None
    return value


OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    status: ItemStatus
    photo_keys: list[str]
    store_department: StoreDepartment | None
    notes: str | None
    created_at: datetime


class RetakePhoto(BaseModel):
    # Counted from 1, in the order the photos were sent.
    number: int
    reason: str


class RetakeDetail(BaseModel):
    kind: Literal["retake"] = "retake"
    message: str
    photos: list[RetakePhoto]


class RepeatPhotoDetail(BaseModel):
    kind: Literal["repeat_photo"] = "repeat_photo"
    message: str
    # The earlier rejected items with one of the same photos, newest rejection first.
    matches: list[RejectedMatch]


class IntakeConflict(BaseModel):
    """The 409 answer when staff should look at the photos again before the item is taken in.

    Nothing is saved, and staff send the same form again with keep_photos or allow_repeat set to
    go on.
    """

    detail: Annotated[RetakeDetail | RepeatPhotoDetail, Field(discriminator="kind")]


class ItemCardRequest(BaseModel):
    """What staff enter, because the model cannot judge these from a photo."""

    condition: Condition
    department: Department | None = None
    size: str | None = None
    size_type: str | None = None
    flaws: list[Flaw] = []
    tested_working: bool | None = None
    complete_in_box: bool | None = None
    accessories_included: str | None = None


class ItemCardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    category: Category
    brand: str | None
    product: str | None
    visible_text: str | None
    search_query: str
    model_confidence: Confidence
    condition: Condition
    department: Department | None
    size: str | None
    size_type: str | None
    flaws: list[Flaw]
    tested_working: bool | None
    complete_in_box: bool | None
    accessories_included: str | None
    color: str | None
    material: str | None
    exact_model: str | None
    platform: str | None
    staff_edited: bool
    staff_confirmed: bool

    @computed_field
    @property
    def needs_confirmation(self) -> bool:
        """True while staff must confirm this card before any search."""
        return not self.staff_confirmed and needs_confirmation(self.brand, self.model_confidence)


class ItemCardEdit(BaseModel):
    """Staff's changes to the card, where a field left out stays as it is. Saving confirms it."""

    model_config = ConfigDict(extra="forbid")

    category: Category | None = None
    brand: OptionalText = None
    product: OptionalText = None
    visible_text: OptionalText = None
    search_query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = (
        None
    )
    condition: Condition | None = None
    department: Department | None = None
    size: OptionalText = None
    size_type: OptionalText = None
    flaws: list[Flaw] | None = None
    tested_working: bool | None = None
    complete_in_box: bool | None = None
    accessories_included: OptionalText = None
    color: OptionalText = None
    material: OptionalText = None
    exact_model: OptionalText = None
    platform: OptionalText = None

    @model_validator(mode="after")
    def required_fields_stay_filled(self) -> Self:
        for name in ("category", "search_query", "condition", "flaws"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} can't be empty")
        return self


class AppraisalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    price_low_cents: int | None
    price_typical_cents: int | None
    price_high_cents: int | None
    net_after_fees_cents: int | None
    comps_count: int
    confidence: Confidence
    recommendation: Recommendation
    rules_config: dict[str, Any]
    explanation: str | None
    # The listings behind the price, cheapest first. Empty for an appraisal with no price.
    comps: list[PricedComp]
    created_at: datetime


REJECTION_REASON_MAX = 200
NOTE_MAX = 500


class OverrideReason(StrEnum):
    """Why staff made the other call from the recommendation, picked from a short list."""

    WRONG_COMPS = "wrong_comps"
    BETTER_CONDITION = "better_condition"
    SELLS_FOR_MORE = "sells_for_more"
    WORSE_CONDITION = "worse_condition"
    SELLS_FOR_LESS = "sells_for_less"
    HARD_TO_SHIP = "hard_to_ship"
    NOT_GENUINE = "not_genuine"
    OTHER = "other"


# The reasons that make sense against each recommendation, so a yes can't say the item is worse.
OVERRIDE_REASONS: dict[DecisionChoice, frozenset[OverrideReason]] = {
    DecisionChoice.YES: frozenset(
        {
            OverrideReason.WRONG_COMPS,
            OverrideReason.BETTER_CONDITION,
            OverrideReason.SELLS_FOR_MORE,
            OverrideReason.OTHER,
        }
    ),
    DecisionChoice.NO: frozenset(
        {
            OverrideReason.WRONG_COMPS,
            OverrideReason.WORSE_CONDITION,
            OverrideReason.SELLS_FOR_LESS,
            OverrideReason.HARD_TO_SHIP,
            OverrideReason.NOT_GENUINE,
            OverrideReason.OTHER,
        }
    ),
}


class DecisionRequest(BaseModel):
    appraisal_id: UUID
    decision: DecisionChoice
    # Needed when the call goes against a yes or no recommendation, and refused otherwise.
    override_reason: OverrideReason | None = None
    # Optional, except that the reason "other" needs one.
    note: Annotated[
        Annotated[str, StringConstraints(max_length=NOTE_MAX)] | None,
        BeforeValidator(_blank_to_none),
    ] = None
    # Both needed with a no and refused with a yes, and written to the triage log.
    rejection_reason: OptionalText = None
    destination: Destination | None = None


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    appraisal_id: UUID
    decision: DecisionChoice
    override_reason: str | None
    note: str | None
    rejection_reason: str | None
    destination: Destination | None
    decided_by: UUID
    decided_at: datetime


class RecentDecision(BaseModel):
    id: UUID
    item_id: UUID
    sku: str
    brand: str | None
    product: str | None
    price_typical_cents: int | None
    decision: DecisionChoice
    # From the triage log, so empty for a manager's no and for decisions made before it existed.
    destination: Destination | None
    decided_by_name: str
    decided_at: datetime


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The channels staff chose from the recommendation, each of which has to take the item.
    channels: Annotated[list[Channel], Field(min_length=1)]


class ListingDraftRead(BaseModel):
    id: UUID
    item_id: UUID
    channel: Channel
    title: str
    description: str
    category: str
    # The categories staff can choose from on this channel for this item.
    category_options: list[str]
    state: DraftState
    source: DraftSource
    fallback_reason: FallbackReason | None
    model_name: str | None
    # Why the model's own draft went to the template, when it did.
    model_flags: list[ClaimFlag]
    # The checker's flags on the text as it stands, against the card as it stands.
    flags: list[ClaimFlag]
    staff_edited: bool
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime


DraftTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX)
]
DraftDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=DESCRIPTION_MAX)
]


class ListingDraftEdit(BaseModel):
    """Staff's changes to one draft, where a field left out stays as it is."""

    model_config = ConfigDict(extra="forbid")

    title: DraftTitle | None = None
    description: DraftDescription | None = None
    category: str | None = None


def _get_item(session: Session, item_id: UUID) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
    return item


def _require_status(item: Item, allowed: set[ItemStatus], action: str) -> None:
    if item.status not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"An item that is {item.status.value} can't be {action}."
        )


def _read_photos(photos: list[UploadFile]) -> list[CheckedPhoto]:
    """The photos after the type and size checks, which refuse a photo outright."""
    if not photos:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Add at least one photo of the item."
        )
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Add at most {MAX_PHOTOS} photos of the item."
        )
    checked: list[CheckedPhoto] = []
    for number, photo in enumerate(photos, start=1):
        try:
            # One byte past the limit is enough to tell a photo is too big.
            checked.append(check_photo(photo.file.read(MAX_PHOTO_BYTES + 1), number))
        except PhotoError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return checked


def _photos_to_retake(checked: list[CheckedPhoto]) -> list[RetakePhoto]:
    """The photos the blur and brightness check finds fault with, which staff may still keep."""
    retakes: list[RetakePhoto] = []
    for number, photo in enumerate(checked, start=1):
        reason = photo_retake_reason(photo.data)
        if reason:
            retakes.append(RetakePhoto(number=number, reason=reason))
    return retakes


@router.post(
    "/items",
    operation_id="create_item",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": IntakeConflict,
            "description": "A photo should be taken again and keep_photos wasn't set, or a photo "
            "matches a rejected item and allow_repeat wasn't set.",
        }
    },
)
def create_item(
    store_department: Annotated[StoreDepartment, Form()],
    profile: CurrentProfile,
    session: SessionDep,
    storage: Annotated[Storage, Depends(get_photo_storage)],
    now: Annotated[datetime, Depends(get_now)],
    photos: Annotated[list[UploadFile] | None, File(description="1 to 4 photos.")] = None,
    notes: Annotated[str | None, Form(max_length=1000)] = None,
    # Staff have seen the prompt to take a photo again and are keeping the photos as they are.
    keep_photos: Annotated[bool, Form()] = False,
    # Staff have seen that a photo matches a rejected item and are taking it in anyway.
    allow_repeat: Annotated[bool, Form()] = False,
) -> ItemRead:
    """Take an item in: check and store its photos, and give it a SKU."""
    checked = _read_photos(photos or [])
    # Asked before the repeat check, because a retaken photo may no longer match.
    if not keep_photos:
        retakes = _photos_to_retake(checked)
        if retakes:
            many = len(retakes) > 1
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                RetakeDetail(
                    message=f"{'Some photos' if many else 'A photo'} may be hard to price from.",
                    photos=retakes,
                ).model_dump(mode="json"),
            )
    hashes = [photo.sha256 for photo in checked]
    if not allow_repeat:
        matches = rejected_matches(session, hashes)
        if matches:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                RepeatPhotoDetail(
                    message="A photo matches an item that was rejected before.", matches=matches
                ).model_dump(mode="json"),
            )
    item_id = uuid4()
    keys = [f"items/{item_id}/{uuid4()}" for _ in checked]
    # Storage can be slow, so save the photos before the SKU, whose number is locked until commit.
    session.commit()
    for number, (key, photo) in enumerate(zip(keys, checked, strict=True), start=1):
        try:
            storage.save(key, photo.data, photo.content_type)
        except PhotoTooLargeError as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Photo {number} is too big to store, so choose a smaller copy.",
            ) from error
        except (OSError, httpx2.HTTPError) as error:
            logger.warning("intake photo %s: %s", number, error)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "We couldn't save the photos just now. Try again."
            ) from error
    item = Item(
        id=item_id,
        sku=next_sku(session, sku_prefix(initials(profile.display_name), store_date(now))),
        lister_id=profile.auth_user_id,
        photo_keys=keys,
        photo_hashes=hashes,
        store_department=store_department,
        notes=_blank_to_none(notes),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return ItemRead.model_validate(item)


@router.post("/items/{item_id}/card", operation_id="create_item_card")
def create_item_card(
    item_id: UUID,
    entries: ItemCardRequest,
    profile: CurrentProfile,
    session: SessionDep,
    storage: Annotated[Storage, Depends(get_photo_storage)],
    providers: Annotated[list[ChatModel], Depends(get_vision_providers)],
) -> ItemCardRead:
    item = _get_item(session, item_id)
    # A repeated call returns the card already made, so the screen can retry a lost response.
    card = session.get(ItemCard, item_id)
    if card is not None:
        return ItemCardRead.model_validate(card)
    _require_status(item, {ItemStatus.INTAKE}, "given a card")
    if not providers:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The vision model isn't set up on this server."
        )
    staff_entries = entries.model_dump(mode="json")
    photo_keys, notes = item.photo_keys, item.notes
    # The model can take a minute, so don't hold a database transaction open across the call.
    session.commit()
    try:
        draft = draft_item_card(photo_keys, staff_entries, notes, storage, providers)
    except UnreadablePhotoError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "That photo can't be opened as an image."
        ) from error
    except (ItemCardError, OSError, httpx2.HTTPError) as error:
        logger.warning("item %s: %s", item_id, error)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "We couldn't read the photo just now. Try again."
        ) from error
    # A second request may have finished during the call, so check again under a lock on the item.
    item = session.get(Item, item_id, with_for_update=True, populate_existing=True)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
    card = session.get(ItemCard, item_id, populate_existing=True)
    if card is None:
        _require_status(item, {ItemStatus.INTAKE}, "given a card")
        card = ItemCard(
            item_id=item_id,
            **draft.model_dump(),
            **entries.model_dump(exclude={"flaws"}),
            flaws=[flaw.value for flaw in entries.flaws],
        )
        item.status = ItemStatus.CARD_READY
        session.add_all([card, item])
    session.commit()
    session.refresh(card)
    return ItemCardRead.model_validate(card)


@router.patch("/items/{item_id}/card", operation_id="confirm_item_card")
def confirm_item_card(
    item_id: UUID, edit: ItemCardEdit, profile: CurrentProfile, session: SessionDep
) -> ItemCardRead:
    """Save what staff checked. An empty body confirms the card as it stands."""
    item = _get_item(session, item_id)
    _require_status(item, {ItemStatus.CARD_READY, ItemStatus.APPRAISED}, "edited")
    card = session.get(ItemCard, item_id)
    if card is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no card yet.")
    for name, value in edit.model_dump(exclude_unset=True).items():
        if name == "flaws":
            value = [flaw.value for flaw in value]
        if getattr(card, name) != value:
            setattr(card, name, value)
            card.staff_edited = True
    card.staff_confirmed = True
    session.add(card)
    session.commit()
    session.refresh(card)
    return ItemCardRead.model_validate(card)


@router.post("/items/{item_id}/appraisals", operation_id="create_appraisal")
def create_appraisal(
    item_id: UUID,
    profile: CurrentProfile,
    session: SessionDep,
    search: Annotated[EbaySearch | None, Depends(get_ebay_search)],
) -> AppraisalRead:
    item = _get_item(session, item_id)
    _require_status(item, {ItemStatus.CARD_READY, ItemStatus.APPRAISED}, "appraised")
    card = session.get(ItemCard, item_id)
    if card is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no card yet.")
    if not card.staff_confirmed and needs_confirmation(card.brand, card.model_confidence):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Confirm the brand and model on the card before searching for this item.",
        )
    result = price_item(card, session, search)
    # The search lets go of the database, so the item may have moved on while it ran.
    item = session.get(Item, item_id, with_for_update=True, populate_existing=True)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
    _require_status(item, {ItemStatus.CARD_READY, ItemStatus.APPRAISED}, "appraised")
    appraisal = Appraisal(item_id=item_id, **result.model_dump())
    item.status = ItemStatus.APPRAISED
    session.add_all([appraisal, item])
    session.commit()
    session.refresh(appraisal)
    return AppraisalRead.model_validate(appraisal)


def _check_override(request: DecisionRequest, recommendation: Recommendation) -> None:
    """A call against a yes or no recommendation needs a reason that fits it, and only that does."""
    against = recommendation is not Recommendation.CHECK and (
        request.decision.value != recommendation.value
    )
    reason = request.override_reason
    if not against:
        if reason is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Only a call against the recommendation needs a reason for disagreeing.",
            )
        return
    if reason is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Choose why it's a {request.decision.value} when the recommendation is "
            f"{recommendation.value}.",
        )
    if reason not in OVERRIDE_REASONS[request.decision]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"That reason doesn't fit a {request.decision.value}.",
        )
    if reason is OverrideReason.OTHER and request.note is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Add a note to say what the reason is."
        )


@router.post(
    "/items/{item_id}/decisions",
    operation_id="create_decision",
    status_code=status.HTTP_201_CREATED,
)
def create_decision(
    item_id: UUID, request: DecisionRequest, profile: CurrentProfile, session: SessionDep
) -> DecisionRead:
    item = _get_item(session, item_id)
    # A declined item can be decided again, because decisions are kept as a history.
    _require_status(item, {ItemStatus.APPRAISED, ItemStatus.DECLINED}, "decided on")
    appraisal = session.get(Appraisal, request.appraisal_id)
    if appraisal is None or appraisal.item_id != item_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That appraisal isn't for this item.")
    _check_override(request, appraisal.recommendation)
    rejected = request.decision == DecisionChoice.NO
    if rejected and request.rejection_reason is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say why it isn't being listed.")
    if rejected and request.destination is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose where the item goes instead."
        )
    if not rejected and (request.rejection_reason or request.destination):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a no has a rejection reason and a destination.",
        )
    if request.rejection_reason and len(request.rejection_reason) > REJECTION_REASON_MAX:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Keep the reason to {REJECTION_REASON_MAX} characters.",
        )
    decision = Decision(
        item_id=item_id,
        appraisal_id=request.appraisal_id,
        decision=request.decision,
        override_reason=request.override_reason,
        note=request.note,
        decided_by=profile.auth_user_id,
        # Stamped here rather than by now(), which repeats within a transaction, so the newest
        # decision is always the one that stands.
        decided_at=datetime.now(UTC),
    )
    # A yes stays appraised until a manager approves it.
    item.status = (
        ItemStatus.DECLINED if request.decision == DecisionChoice.NO else ItemStatus.APPRAISED
    )
    if request.decision == DecisionChoice.YES:
        # A listing a manager turned down goes back to staff to edit and send again.
        for draft in _item_drafts(session, item_id):
            if draft.state is DraftState.REJECTED:
                draft.state = DraftState.DRAFT
                draft.reviewed_by = None
                draft.reviewed_at = None
                session.add(draft)
    triage = TriageEntry(
        item_id=item_id,
        decision_id=decision.id,
        submitted_by=item.lister_id,
        store_department=item.store_department,
        outcome=TriageOutcome.REJECTED if rejected else TriageOutcome.ACCEPTED,
        rejection_reason=request.rejection_reason,
        destination=request.destination,
        recorded_at=decision.decided_at,
    )
    session.add_all([decision, item])
    # The triage row refers to the decision, so the decision goes in first.
    session.flush()
    session.add(triage)
    session.commit()
    session.refresh(decision)
    return DecisionRead.model_validate(
        decision.model_dump()
        | {"rejection_reason": triage.rejection_reason, "destination": triage.destination}
    )


@router.get("/decisions", operation_id="list_decisions")
def list_decisions(
    profile: CurrentProfile,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RecentDecision]:
    """Newest first. Managers see every decision and staff see their own."""
    query = (
        sa.select(
            col(Decision.id),
            col(Decision.item_id),
            col(Item.sku),
            col(ItemCard.brand),
            col(ItemCard.product),
            col(Appraisal.price_typical_cents),
            col(Decision.decision),
            col(TriageEntry.destination),
            col(Profile.display_name).label("decided_by_name"),
            col(Decision.decided_at),
        )
        .join(Item, col(Decision.item_id) == col(Item.id))
        .join(Appraisal, col(Decision.appraisal_id) == col(Appraisal.id))
        .join(ItemCard, col(Decision.item_id) == col(ItemCard.item_id))
        .join(Profile, col(Decision.decided_by) == col(Profile.auth_user_id))
        .outerjoin(TriageEntry, col(TriageEntry.decision_id) == col(Decision.id))
        .order_by(col(Decision.decided_at).desc(), col(Decision.id))
        .limit(limit)
    )
    if profile.role != Role.MANAGER:
        query = query.where(col(Decision.decided_by) == profile.auth_user_id)
    rows = session.connection().execute(query).mappings()
    return [RecentDecision.model_validate(dict(row)) for row in rows]


def latest_decision(session: Session, item_id: UUID) -> Decision | None:
    """The decision that stands, which is the newest one, whether staff or a manager made it."""
    return session.exec(
        select(Decision)
        .where(Decision.item_id == item_id)
        .order_by(col(Decision.decided_at).desc(), col(Decision.id))
        .limit(1)
    ).first()


def _require_listing(session: Session, item: Item, action: str) -> ItemCard:
    """The card of an item staff said yes to, which is the only kind that gets a listing."""
    _require_status(item, {ItemStatus.APPRAISED}, action)
    latest = latest_decision(session, item.id)
    if latest is None or latest.decision is not DecisionChoice.YES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Decide to list this item before writing its listing."
        )
    card = session.get(ItemCard, item.id)
    if card is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no card yet.")
    return card


def _item_drafts(session: Session, item_id: UUID) -> list[ListingDraft]:
    drafts = session.exec(select(ListingDraft).where(ListingDraft.item_id == item_id)).all()
    return sorted(drafts, key=lambda draft: list(Channel).index(draft.channel))


def _draft_read(draft: ListingDraft, card: ItemCard) -> ListingDraftRead:
    return ListingDraftRead(
        id=draft.id,
        item_id=draft.item_id,
        channel=draft.channel,
        title=draft.title,
        description=draft.description,
        category=draft.category,
        category_options=list(category_options(draft.channel, card.category)),
        state=draft.state,
        source=draft.source,
        fallback_reason=draft.fallback_reason,
        model_name=draft.model_name,
        model_flags=[ClaimFlag.model_validate(flag) for flag in draft.model_flags],
        flags=check_listing(draft.title, draft.description, ListingFacts.from_card(card)),
        staff_edited=draft.staff_edited,
        submitted_at=draft.submitted_at,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


@router.get("/items/{item_id}/channels", operation_id="get_channel_recommendation")
def get_channel_recommendation(
    item_id: UUID,
    profile: CurrentProfile,
    session: SessionDep,
    providers: Annotated[list[ChatModel], Depends(get_reason_providers)],
    today: Annotated[date, Depends(get_today)],
) -> ChannelRecommendation:
    """Which channels can take the item and whether to list it now, for staff to choose from.

    The timing reads the seasonal calendar as it is now, so a change on the Settings page shows
    on the next read.
    """
    item = _get_item(session, item_id)
    card = _require_listing(session, item, "listed")
    facts = ListingFacts.from_card(card)
    calendar = read_store_settings(session).seasonal_calendar
    # The model can take a while, so don't hold a database transaction open across the call.
    session.commit()
    return recommend(facts, calendar, today, providers)


@router.post("/items/{item_id}/drafts", operation_id="create_listing_drafts")
def create_listing_drafts(
    item_id: UUID,
    request: DraftRequest,
    profile: CurrentProfile,
    session: SessionDep,
    providers: Annotated[list[ChatModel], Depends(get_draft_providers)],
    today: Annotated[date, Depends(get_today)],
) -> list[ListingDraftRead]:
    """Draft the listing for each channel staff chose, and return all of the item's drafts.

    Drafting also holds the item until its season when the timing hint says so, by setting its
    release month, which the approval step reads. An item that already has drafts keeps them and
    its release month, whatever the request names, so the screen can retry a lost response.
    """
    item = _get_item(session, item_id)
    card = _require_listing(session, item, "listed")
    if not _item_drafts(session, item_id):
        facts = ListingFacts.from_card(card)
        advice = advise(facts, read_store_settings(session).seasonal_calendar, today)
        refused = [
            option.why_not
            for option in advice.channels
            if option.channel in request.channels and option.why_not
        ]
        if refused:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, " ".join(refused))
        channels = [channel for channel in Channel if channel in request.channels]
        # The model can take a while, so don't hold a database transaction open across the calls.
        session.commit()
        results = {channel: draft_listing(facts, channel, providers) for channel in channels}
        # Another request may have drafted meanwhile, so check again under a lock on the item.
        item = session.get(Item, item_id, with_for_update=True, populate_existing=True)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
        _require_listing(session, item, "listed")
        if _item_drafts(session, item_id):
            results = {}
        else:
            item.release_month = advice.timing.release_month
            session.add(item)
        for channel, result in results.items():
            session.add(
                ListingDraft(
                    item_id=item_id,
                    channel=channel,
                    title=result.text.title,
                    description=result.text.description,
                    category=result.text.category,
                    source=result.source,
                    fallback_reason=result.fallback_reason,
                    model_name=result.model_name,
                    model_flags=[flag.model_dump(mode="json") for flag in result.model_flags],
                    created_by=profile.auth_user_id,
                )
            )
        session.commit()
    card = session.get(ItemCard, item_id, populate_existing=True)
    assert card is not None
    return [_draft_read(draft, card) for draft in _item_drafts(session, item_id)]


@router.get("/items/{item_id}/drafts", operation_id="list_listing_drafts")
def list_listing_drafts(
    item_id: UUID, profile: CurrentProfile, session: SessionDep
) -> list[ListingDraftRead]:
    _get_item(session, item_id)
    card = session.get(ItemCard, item_id)
    if card is None:
        return []
    return [_draft_read(draft, card) for draft in _item_drafts(session, item_id)]


@router.patch("/items/{item_id}/drafts/{channel}", operation_id="edit_listing_draft")
def edit_listing_draft(
    item_id: UUID,
    channel: Channel,
    edit: ListingDraftEdit,
    profile: CurrentProfile,
    session: SessionDep,
) -> ListingDraftRead:
    """Save staff's changes, which the checker reads again like the model's draft."""
    item = session.get(Item, item_id, with_for_update=True)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
    card = _require_listing(session, item, "edited")
    draft = next((d for d in _item_drafts(session, item_id) if d.channel is channel), None)
    if draft is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"This item has no draft for {CHANNEL_NAMES[channel]}."
        )
    if draft.state is not DraftState.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This draft is already waiting for a manager, so it can't be edited.",
        )
    changes = edit.model_dump(exclude_unset=True)
    if "category" in changes:
        options = category_options(channel, card.category)
        chosen = next(
            (o for o in options if o.lower() == (changes["category"] or "").lower()), None
        )
        if chosen is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Choose one of {CHANNEL_NAMES[channel]}'s categories for this item.",
            )
        changes["category"] = chosen
    for name, value in changes.items():
        if value is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name} can't be empty.")
        if getattr(draft, name) != value:
            setattr(draft, name, value)
            draft.staff_edited = True
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return _draft_read(draft, card)


@router.post("/items/{item_id}/drafts/submit", operation_id="submit_listing_drafts")
def submit_listing_drafts(
    item_id: UUID, profile: CurrentProfile, session: SessionDep
) -> list[ListingDraftRead]:
    """Send every draft on to manager approval, once none of them has a flagged claim."""
    item = session.get(Item, item_id, with_for_update=True)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That item doesn't exist.")
    card = _require_listing(session, item, "sent for approval")
    drafts = _item_drafts(session, item_id)
    if not drafts:
        raise HTTPException(status.HTTP_409_CONFLICT, "Write the listing drafts first.")
    facts = ListingFacts.from_card(card)
    pending = [draft for draft in drafts if draft.state is DraftState.DRAFT]
    flagged = [
        CHANNEL_NAMES[draft.channel]
        for draft in pending
        if check_listing(draft.title, draft.description, facts)
    ]
    if flagged:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Fix the flagged claims on {' and '.join(flagged)} before sending the listing on.",
        )
    now = datetime.now(UTC)
    for draft in pending:
        draft.state = DraftState.AWAITING_APPROVAL
        draft.submitted_by = profile.auth_user_id
        draft.submitted_at = now
        session.add(draft)
    session.commit()
    return [_draft_read(draft, card) for draft in _item_drafts(session, item_id)]
