"""The staff path from a photo to a saved decision, one route per step."""

import logging
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any, Self
from uuid import UUID, uuid4

import httpx2
import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    computed_field,
    model_validator,
)
from sqlmodel import Session, col

from app.ai import AINotConfiguredError, ChatModel, get_chat_model, get_fallback_chat_model
from app.auth import CurrentProfile
from app.comps import EbaySearch, serpapi_ebay_search
from app.db import get_session
from app.models import (
    Appraisal,
    Category,
    Condition,
    Confidence,
    Decision,
    DecisionChoice,
    Department,
    Flaw,
    Item,
    ItemCard,
    ItemStatus,
    Profile,
    Recommendation,
    Role,
)
from app.pipeline import (
    draft_item_card,
    needs_confirmation,
    placeholder_photo_hash,
    placeholder_sku,
    price_item,
)
from app.settings import get_settings
from app.storage import Storage, get_storage
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
    created_at: datetime


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
    created_at: datetime


class DecisionRequest(BaseModel):
    appraisal_id: UUID
    decision: DecisionChoice
    override_reason: str | None = None
    note: str | None = None


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    appraisal_id: UUID
    decision: DecisionChoice
    override_reason: str | None
    note: str | None
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
    decided_by_name: str
    decided_at: datetime


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


@router.post("/items", operation_id="create_item", status_code=status.HTTP_201_CREATED)
def create_item(
    photo: Annotated[UploadFile, File()],
    profile: CurrentProfile,
    session: SessionDep,
    storage: Annotated[Storage, Depends(get_photo_storage)],
) -> ItemRead:
    # PLACEHOLDER: #9 adds the file type and size checks, the real photo hash and up to 4 photos.
    data = photo.file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That photo is empty.")
    item_id = uuid4()
    key = f"items/{item_id}/{uuid4()}"
    storage.save(key, data, photo.content_type or "application/octet-stream")
    item = Item(
        id=item_id,
        sku=placeholder_sku(item_id),
        lister_id=profile.auth_user_id,
        photo_keys=[key],
        photo_hash=placeholder_photo_hash(item_id),
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
    decision = Decision(
        item_id=item_id,
        appraisal_id=request.appraisal_id,
        decision=request.decision,
        override_reason=request.override_reason,
        note=request.note,
        decided_by=profile.auth_user_id,
    )
    # A yes stays appraised until a manager approves it, which comes after the MVP.
    item.status = (
        ItemStatus.DECLINED if request.decision == DecisionChoice.NO else ItemStatus.APPRAISED
    )
    session.add_all([decision, item])
    session.commit()
    session.refresh(decision)
    return DecisionRead.model_validate(decision)


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
            col(Profile.display_name).label("decided_by_name"),
            col(Decision.decided_at),
        )
        .join(Item, col(Decision.item_id) == col(Item.id))
        .join(Appraisal, col(Decision.appraisal_id) == col(Appraisal.id))
        .join(ItemCard, col(Decision.item_id) == col(ItemCard.item_id))
        .join(Profile, col(Decision.decided_by) == col(Profile.auth_user_id))
        .order_by(col(Decision.decided_at).desc(), col(Decision.id))
        .limit(limit)
    )
    if profile.role != Role.MANAGER:
        query = query.where(col(Decision.decided_by) == profile.auth_user_id)
    rows = session.connection().execute(query).mappings()
    return [RecentDecision.model_validate(dict(row)) for row in rows]
