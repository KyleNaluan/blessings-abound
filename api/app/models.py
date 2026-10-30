"""Database tables. The design and the reasons behind it are in docs/database.md."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

# Give every constraint a predictable name, so migrations can refer to them.
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

USERNAME_PATTERN = "^[a-z0-9._-]+$"
MAX_PHOTOS = 4


class Role(StrEnum):
    STAFF = "staff"
    MANAGER = "manager"


class ItemStatus(StrEnum):
    INTAKE = "intake"
    CARD_READY = "card_ready"
    APPRAISED = "appraised"
    DECLINED = "declined"
    APPROVED = "approved"
    HELD_FOR_SEASON = "held_for_season"
    LISTED = "listed"
    SOLD = "sold"
    PICKED = "picked"


class Category(StrEnum):
    APPAREL = "apparel"
    ELECTRONICS_GAMES = "electronics_games"


class Condition(StrEnum):
    NEW_WITH_TAGS = "new_with_tags"
    NEW_WITHOUT_TAGS = "new_without_tags"
    PRE_OWNED = "pre_owned"


class Department(StrEnum):
    MENS = "mens"
    WOMENS = "womens"
    KIDS = "kids"


class Flaw(StrEnum):
    STAINS = "stains"
    TEARS = "tears"
    SCUFFS = "scuffs"
    MISSING_PARTS = "missing_parts"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Recommendation(StrEnum):
    YES = "yes"
    NO = "no"
    CHECK = "check"


class DecisionChoice(StrEnum):
    YES = "yes"
    NO = "no"


def _enum_type(enum: type[StrEnum], name: str) -> sa.Enum:
    # Text with a check constraint rather than a Postgres enum, so a later migration can change the
    # allowed values by swapping the constraint.
    return sa.Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )


def _created_at() -> Any:
    return Field(
        default=None,
        sa_column=sa.Column(
            sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def _updated_at() -> Any:
    return Field(
        default=None,
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"  # type: ignore[assignment]
    __table_args__ = (
        sa.CheckConstraint(f"username ~ '{USERNAME_PATTERN}'", name="username_format"),
        sa.CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    # The Supabase Auth user id, with no foreign key to auth.users, which local Postgres lacks.
    auth_user_id: UUID = Field(primary_key=True)
    username: str = Field(sa_type=sa.Text, unique=True)
    display_name: str = Field(sa_type=sa.Text)
    email: str | None = Field(default=None, sa_type=sa.Text, unique=True)
    role: Role = Field(
        default=Role.STAFF,
        sa_column=sa.Column(_enum_type(Role, "role"), nullable=False, server_default=Role.STAFF),
    )
    is_active: bool = Field(default=True, sa_column_kwargs={"server_default": sa.true()})
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class Item(SQLModel, table=True):
    __tablename__ = "items"  # type: ignore[assignment]
    __table_args__ = (
        sa.CheckConstraint(
            f"cardinality(photo_keys) BETWEEN 1 AND {MAX_PHOTOS}", name="photo_keys_count"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    sku: str = Field(sa_type=sa.Text, unique=True)
    lister_id: UUID = Field(foreign_key="profiles.auth_user_id", index=True)
    status: ItemStatus = Field(
        default=ItemStatus.INTAKE,
        sa_column=sa.Column(
            _enum_type(ItemStatus, "status"), nullable=False, server_default=ItemStatus.INTAKE
        ),
    )
    photo_keys: list[str] = Field(sa_column=sa.Column(ARRAY(sa.Text), nullable=False))
    # Not unique, because a repeat photo prompts staff rather than being refused.
    photo_hash: str = Field(sa_type=sa.Text, index=True)
    notes: str | None = Field(default=None, sa_type=sa.Text)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class ItemCard(SQLModel, table=True):
    __tablename__ = "item_cards"  # type: ignore[assignment]
    __table_args__ = (
        sa.CheckConstraint(
            "flaws <@ ARRAY[{}]::text[]".format(", ".join(f"'{flaw.value}'" for flaw in Flaw)),
            name="flaws_known",
        ),
    )

    item_id: UUID = Field(foreign_key="items.id", primary_key=True)
    # From the vision model, and staff can edit them before any search is spent.
    category: Category = Field(
        sa_column=sa.Column(_enum_type(Category, "category"), nullable=False)
    )
    brand: str | None = Field(default=None, sa_type=sa.Text)
    product: str | None = Field(default=None, sa_type=sa.Text)
    visible_text: str | None = Field(default=None, sa_type=sa.Text)
    search_query: str = Field(sa_type=sa.Text)
    model_confidence: Confidence = Field(
        sa_column=sa.Column(_enum_type(Confidence, "model_confidence"), nullable=False)
    )
    # From staff, because the model cannot judge them from a photo.
    condition: Condition = Field(
        sa_column=sa.Column(_enum_type(Condition, "condition"), nullable=False)
    )
    department: Department | None = Field(
        default=None, sa_column=sa.Column(_enum_type(Department, "department"))
    )
    size: str | None = Field(default=None, sa_type=sa.Text)
    size_type: str | None = Field(default=None, sa_type=sa.Text)
    flaws: list[str] = Field(
        default_factory=list,
        sa_column=sa.Column(ARRAY(sa.Text), nullable=False, server_default="{}"),
    )
    tested_working: bool | None = Field(default=None)
    complete_in_box: bool | None = Field(default=None)
    accessories_included: str | None = Field(default=None, sa_type=sa.Text)
    # Proposed by the model and confirmed by staff.
    color: str | None = Field(default=None, sa_type=sa.Text)
    material: str | None = Field(default=None, sa_type=sa.Text)
    exact_model: str | None = Field(default=None, sa_type=sa.Text)
    platform: str | None = Field(default=None, sa_type=sa.Text)
    staff_edited: bool = Field(default=False, sa_column_kwargs={"server_default": sa.false()})
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class Appraisal(SQLModel, table=True):
    __tablename__ = "appraisals"  # type: ignore[assignment]
    __table_args__ = (
        sa.UniqueConstraint("id", "item_id"),
        sa.CheckConstraint("price_low_cents >= 0", name="price_low_cents_non_negative"),
        sa.CheckConstraint("price_typical_cents >= 0", name="price_typical_cents_non_negative"),
        sa.CheckConstraint("price_high_cents >= 0", name="price_high_cents_non_negative"),
        sa.CheckConstraint(
            "price_low_cents <= price_typical_cents AND price_typical_cents <= price_high_cents",
            name="price_range_ordered",
        ),
        sa.CheckConstraint("comps_count >= 0", name="comps_count_non_negative"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id", index=True)
    # The prices are empty when there are no comps, which gives the recommendation "check".
    price_low_cents: int | None = Field(default=None)
    price_typical_cents: int | None = Field(default=None)
    price_high_cents: int | None = Field(default=None)
    # The one cents column that may go below zero, because fees can exceed a cheap item's price.
    net_after_fees_cents: int | None = Field(default=None)
    comps_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    confidence: Confidence = Field(
        sa_column=sa.Column(_enum_type(Confidence, "confidence"), nullable=False)
    )
    recommendation: Recommendation = Field(
        sa_column=sa.Column(_enum_type(Recommendation, "recommendation"), nullable=False)
    )
    rules_config: dict[str, Any] = Field(sa_column=sa.Column(JSONB, nullable=False))
    explanation: str | None = Field(default=None, sa_type=sa.Text)
    created_at: datetime = _created_at()


class Decision(SQLModel, table=True):
    __tablename__ = "decisions"  # type: ignore[assignment]
    __table_args__ = (
        # Keeps a decision from pointing at another item's appraisal.
        sa.ForeignKeyConstraint(
            ["appraisal_id", "item_id"], ["appraisals.id", "appraisals.item_id"]
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id", index=True)
    appraisal_id: UUID
    decision: DecisionChoice = Field(
        sa_column=sa.Column(_enum_type(DecisionChoice, "decision"), nullable=False)
    )
    override_reason: str | None = Field(default=None, sa_type=sa.Text)
    note: str | None = Field(default=None, sa_type=sa.Text)
    decided_by: UUID = Field(foreign_key="profiles.auth_user_id", index=True)
    decided_at: datetime = Field(
        default=None,
        sa_column=sa.Column(
            sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
        ),
    )
