"""Database tables. The design and the reasons behind it are in docs/database.md."""

from datetime import date, datetime
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


class AccountStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    TEMPORARY_PASSWORD = "temporary_password"
    DEACTIVATED = "deactivated"


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


class SettingKey(StrEnum):
    """The sections of the Settings page, each stored as one row of `settings`."""

    BOX_SIZES = "box_sizes"
    SEASONAL_CALENDAR = "seasonal_calendar"
    WORTH_LISTING = "worth_listing"
    FEES = "fees"
    ASK_TO_SALE = "ask_to_sale"
    SHIPPING_WEIGHT = "shipping_weight"
    CHANNEL_B_FEES = "channel_b_fees"


class Channel(StrEnum):
    """The two mock channels, named like their schemas: A is eBay-style, B is apparel only."""

    CHANNEL_A = "channel_a"
    CHANNEL_B = "channel_b"


class DraftState(StrEnum):
    # Staff are still editing it.
    DRAFT = "draft"
    # Staff sent it on, and the manager approval step reads it from here.
    AWAITING_APPROVAL = "awaiting_approval"
    # A manager approved the listing, so it can be published once the item is stored.
    APPROVED = "approved"
    # A manager turned the item down, which also records a no decision.
    REJECTED = "rejected"


class DraftSource(StrEnum):
    MODEL = "model"
    TEMPLATE = "template"


class FallbackReason(StrEnum):
    # The claim checker flagged the model's draft.
    FLAGGED = "flagged"
    # Every provider failed or sent back something unusable.
    MODEL_FAILED = "model_failed"
    # No model is set up on this server.
    NOT_CONFIGURED = "not_configured"


class ListingStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SOLD = "sold"
    ENDED = "ended"
    REJECTED = "rejected"
    FAILED = "failed"


class SaleSource(StrEnum):
    WEBHOOK = "webhook"
    POLLING = "polling"


class SyncEvent(StrEnum):
    PUBLISHED = "published"
    PUBLISH_REJECTED = "publish_rejected"
    PUBLISH_FAILED = "publish_failed"
    PUBLISH_GAVE_UP = "publish_gave_up"
    PUBLISH_SKIPPED = "publish_skipped"
    SALE_RECORDED = "sale_recorded"
    DELISTED = "delisted"
    DELIST_FAILED = "delist_failed"
    DELIST_GAVE_UP = "delist_gave_up"
    DELIST_FOUND_SOLD = "delist_found_sold"
    FLAGGED = "flagged"
    ORDER_CANCELLED = "order_cancelled"
    CANCEL_REJECTED = "cancel_rejected"
    CANCEL_FAILED = "cancel_failed"
    CANCEL_GAVE_UP = "cancel_gave_up"


class ConflictKind(StrEnum):
    DOUBLE_SALE = "double_sale"
    STALE_LISTING = "stale_listing"
    UNKNOWN_LISTING = "unknown_listing"


class JobKind(StrEnum):
    PUBLISH_LISTING = "publish_listing"
    END_LISTING = "end_listing"
    # Cancelling the later order of a double sale, which someone asked for on Needs Attention.
    CANCEL_ORDER = "cancel_order"


class JobStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


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
    must_change_password: bool = Field(
        default=False, sa_column_kwargs={"server_default": sa.false()}
    )
    invited_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    # On Auth's clock, because it is compared with the issue time on Auth's tokens.
    temporary_password_issued_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),  # pyright: ignore[reportArgumentType]
    )
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    @property
    def status(self) -> AccountStatus:
        if not self.is_active:
            return AccountStatus.DEACTIVATED
        if not self.must_change_password:
            return AccountStatus.ACTIVE
        return AccountStatus.INVITED if self.invited_at else AccountStatus.TEMPORARY_PASSWORD


class SignInAttempt(SQLModel, table=True):
    """One username sign-in that was wrong, or is still waiting for Auth's answer.

    The username is hashed because people sometimes type a password into that box.
    """

    __tablename__ = "sign_in_attempts"  # type: ignore[assignment]
    __table_args__ = (sa.Index("ix_sign_in_attempts_lookup", "username_hash", "attempted_at"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username_hash: str = Field(sa_type=sa.Text)
    attempted_at: datetime = Field(
        default=None,
        sa_column=sa.Column(
            sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
        ),
    )


class Item(SQLModel, table=True):
    __tablename__ = "items"  # type: ignore[assignment]
    __table_args__ = (
        sa.CheckConstraint(
            f"cardinality(photo_keys) BETWEEN 1 AND {MAX_PHOTOS}", name="photo_keys_count"
        ),
        sa.CheckConstraint("EXTRACT(DAY FROM release_month) = 1", name="release_month_first_day"),
        sa.CheckConstraint("package_weight_oz > 0", name="package_weight_oz_positive"),
        sa.CheckConstraint(
            "(package_weight_oz IS NULL) = (box_code IS NULL)", name="package_weight_with_box"
        ),
        sa.CheckConstraint(
            "location_code IS NULL OR box_code IS NOT NULL", name="location_after_package"
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
    # The first day of the month a held item is released in, which the timing hint sets.
    release_month: date | None = Field(default=None)
    # The package, which a manager enters before approving Channel A and at the latest when storing.
    package_weight_oz: float | None = Field(default=None)
    # One of the codes in the Settings box sizes, copied, and added to the SKU as its suffix.
    box_code: str | None = Field(default=None, sa_type=sa.Text)
    # The shelf or bin the item is stored on, entered after approval.
    location_code: str | None = Field(default=None, sa_type=sa.Text)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    @property
    def full_sku(self) -> str | None:
        """The SKU with its box-size suffix, such as RT10272601 12x12x6, once a box is chosen."""
        return f"{self.sku} {self.box_code}" if self.box_code else None


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
    staff_confirmed: bool = Field(default=False, sa_column_kwargs={"server_default": sa.false()})
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


class CompSearch(SQLModel, table=True):
    """One SerpApi eBay response, kept so repeats and tests spend no searches.

    A refresh adds a new row instead of replacing the old one, so the rows of the current month
    are also the count of searches spent against the monthly budget.
    """

    __tablename__ = "comp_searches"  # type: ignore[assignment]
    __table_args__ = (
        sa.Index(
            "ix_comp_searches_lookup", "engine", "query", "condition", "buying_format", "fetched_at"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    engine: str = Field(sa_type=sa.Text)
    query: str = Field(sa_type=sa.Text)
    # The eBay condition ids joined with "|", as sent in LH_ItemCondition.
    condition: str = Field(sa_type=sa.Text)
    buying_format: str = Field(sa_type=sa.Text)
    response: dict[str, Any] = Field(sa_column=sa.Column(JSONB, nullable=False))
    fetched_at: datetime = Field(
        default=None,
        sa_column=sa.Column(
            sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


class StoreSetting(SQLModel, table=True):
    """One section of the Settings page, such as the box sizes or the fees.

    The value's shape and rules live in `app/store_settings.py`, which checks every write.
    """

    __tablename__ = "settings"  # type: ignore[assignment]

    key: SettingKey = Field(
        sa_column=sa.Column(_enum_type(SettingKey, "key"), primary_key=True),
    )
    value: dict[str, Any] = Field(sa_column=sa.Column(JSONB, nullable=False))
    # Empty for the values the migration seeded, until a manager saves the section.
    updated_by: UUID | None = Field(default=None, foreign_key="profiles.auth_user_id")
    updated_at: datetime = _updated_at()


class ListingDraft(SQLModel, table=True):
    """The listing text for one item on one channel, written by the model or the fixed template.

    The claim checker's flags are worked out from the current card whenever a draft is read, so
    they never go stale, and only the flags that sent a model draft to the template are stored.
    """

    __tablename__ = "listing_drafts"  # type: ignore[assignment]
    __table_args__ = (
        sa.UniqueConstraint("item_id", "channel"),
        sa.CheckConstraint(
            "(source = 'model') = (fallback_reason IS NULL)", name="fallback_reason_with_template"
        ),
        sa.CheckConstraint(
            # Any state after draft has been sent on by someone, which later states keep.
            "state = 'draft' OR (submitted_at IS NOT NULL AND submitted_by IS NOT NULL)",
            name="submitted_after_draft",
        ),
        sa.CheckConstraint(
            # An approved or rejected listing names the manager who reviewed it.
            "(state IN ('approved', 'rejected')) = "
            "(reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)",
            name="reviewed_after_approval",
        ),
        sa.CheckConstraint("price_override_cents > 0", name="price_override_cents_positive"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Not indexed alone, because the unique constraint on the item and channel starts with it.
    item_id: UUID = Field(foreign_key="items.id")
    channel: Channel = Field(sa_column=sa.Column(_enum_type(Channel, "channel"), nullable=False))
    title: str = Field(sa_type=sa.Text)
    description: str = Field(sa_type=sa.Text)
    # One of the channel's own categories for the item's category, see app/listing_drafts.py.
    category: str = Field(sa_type=sa.Text)
    state: DraftState = Field(
        default=DraftState.DRAFT,
        sa_column=sa.Column(
            _enum_type(DraftState, "state"), nullable=False, server_default=DraftState.DRAFT
        ),
    )
    source: DraftSource = Field(
        sa_column=sa.Column(_enum_type(DraftSource, "source"), nullable=False)
    )
    fallback_reason: FallbackReason | None = Field(
        default=None, sa_column=sa.Column(_enum_type(FallbackReason, "fallback_reason"))
    )
    # The provider that answered, even when its draft was flagged.
    model_name: str | None = Field(default=None, sa_type=sa.Text)
    # The checker's flags on the model's draft, which are why a flagged draft became the template.
    model_flags: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=sa.Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    staff_edited: bool = Field(default=False, sa_column_kwargs={"server_default": sa.false()})
    created_by: UUID = Field(foreign_key="profiles.auth_user_id")
    submitted_by: UUID | None = Field(default=None, foreign_key="profiles.auth_user_id")
    submitted_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    # The manager's price for this channel, in place of the appraisal's typical price.
    price_override_cents: int | None = Field(default=None)
    reviewed_by: UUID | None = Field(default=None, foreign_key="profiles.auth_user_id")
    reviewed_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class Listing(SQLModel, table=True):
    """One item on one channel, as the master record sees it.

    The status changes only on what the channel has confirmed, so a listing being taken down
    stays active, with an end_listing job, until the channel says it has ended.
    """

    __tablename__ = "listings"  # type: ignore[assignment]
    __table_args__ = (
        sa.UniqueConstraint("item_id", "channel"),
        sa.UniqueConstraint("channel", "channel_listing_id"),
        sa.CheckConstraint("price_cents > 0", name="price_cents_positive"),
    )

    # Also the external_ref the channel keeps, which makes a repeated publish return one listing.
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id", index=True)
    channel: Channel = Field(sa_column=sa.Column(_enum_type(Channel, "channel"), nullable=False))
    # The channel's own id, empty until the channel has confirmed the publish.
    channel_listing_id: str | None = Field(default=None, sa_type=sa.Text)
    price_cents: int
    # What was sent, or is to be sent, so a publish retried from jobs sends the same listing.
    content: dict[str, Any] = Field(sa_column=sa.Column(JSONB, nullable=False))
    status: ListingStatus = Field(
        default=ListingStatus.PENDING,
        sa_column=sa.Column(
            _enum_type(ListingStatus, "status"),
            nullable=False,
            server_default=ListingStatus.PENDING,
        ),
    )
    # Why the channel refused the listing or the publish gave up.
    status_detail: str | None = Field(default=None, sa_type=sa.Text)
    approved_by: UUID = Field(foreign_key="profiles.auth_user_id", index=True)
    approved_at: datetime = Field(sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    published_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    sold_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    ended_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class SaleEvent(SQLModel, table=True):
    """One order a channel reported, kept once however many times the webhook and polling see it."""

    __tablename__ = "sale_events"  # type: ignore[assignment]
    __table_args__ = (
        sa.UniqueConstraint("channel", "channel_order_id"),
        sa.CheckConstraint("price_cents >= 0", name="price_cents_non_negative"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    item_id: UUID = Field(foreign_key="items.id", index=True)
    listing_id: UUID = Field(foreign_key="listings.id", index=True)
    channel: Channel = Field(sa_column=sa.Column(_enum_type(Channel, "channel"), nullable=False))
    channel_order_id: str = Field(sa_type=sa.Text)
    price_cents: int
    # On the channel's clock.
    sold_at: datetime = Field(sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    source: SaleSource = Field(
        sa_column=sa.Column(_enum_type(SaleSource, "source"), nullable=False)
    )
    received_at: datetime = Field(
        default=None,
        sa_column=sa.Column(
            sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # Set once the channel confirms it cancelled the order, the later one of a double sale.
    cancelled_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]


class SyncLogEntry(SQLModel, table=True):
    """What sync did, one row per change, and each Needs Attention flag with its resolution.

    A flag is a row with `event` flagged and a `conflict`, and it stays open until `resolved_at` is
    set. Its `conflict_key` is unique among open flags, so polling raises each conflict once.
    """

    __tablename__ = "sync_log"  # type: ignore[assignment]
    __table_args__ = (
        sa.CheckConstraint(
            "(event = 'flagged') = (conflict IS NOT NULL) "
            "AND (conflict IS NULL) = (conflict_key IS NULL)",
            name="flag_has_conflict",
        ),
        sa.CheckConstraint(
            "conflict IS NOT NULL OR (resolved_at IS NULL AND resolved_by IS NULL "
            "AND resolution IS NULL)",
            name="only_flags_resolve",
        ),
        sa.Index(
            "uq_sync_log_open_conflict_key",
            "conflict_key",
            unique=True,
            postgresql_where=sa.text("conflict_key IS NOT NULL AND resolved_at IS NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    event: SyncEvent = Field(sa_column=sa.Column(_enum_type(SyncEvent, "event"), nullable=False))
    channel: Channel | None = Field(
        default=None, sa_column=sa.Column(_enum_type(Channel, "channel"))
    )
    item_id: UUID | None = Field(default=None, foreign_key="items.id", index=True)
    listing_id: UUID | None = Field(default=None, foreign_key="listings.id", index=True)
    channel_listing_id: str | None = Field(default=None, sa_type=sa.Text)
    channel_order_id: str | None = Field(default=None, sa_type=sa.Text)
    source: SaleSource | None = Field(
        default=None, sa_column=sa.Column(_enum_type(SaleSource, "source"))
    )
    # A plain sentence for the log and the Needs Attention screen.
    message: str = Field(sa_type=sa.Text)
    detail: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    conflict: ConflictKind | None = Field(
        default=None, sa_column=sa.Column(_enum_type(ConflictKind, "conflict"))
    )
    conflict_key: str | None = Field(default=None, sa_type=sa.Text)
    resolved_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    resolved_by: UUID | None = Field(default=None, foreign_key="profiles.auth_user_id")
    resolution: str | None = Field(default=None, sa_type=sa.Text)
    created_at: datetime = Field(
        default=None,
        sa_column=sa.Column(
            sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
        ),
    )


class FlagExplanation(SQLModel, table=True):
    """The plain-language explanation and suggested fix shown with one Needs Attention flag.

    Code finds and flags every conflict, and the model only words what code already worked out,
    so a flag shows straight away with the fixed text in app/attention.py until this row exists.
    """

    __tablename__ = "flag_explanations"  # type: ignore[assignment]
    __table_args__ = (
        sa.CheckConstraint(
            "(source = 'model') = (fallback_reason IS NULL)", name="fallback_reason_with_template"
        ),
    )

    flag_id: UUID = Field(foreign_key="sync_log.id", primary_key=True)
    explanation: str = Field(sa_type=sa.Text)
    suggested_fix: str = Field(sa_type=sa.Text)
    source: DraftSource = Field(
        sa_column=sa.Column(_enum_type(DraftSource, "source"), nullable=False)
    )
    fallback_reason: FallbackReason | None = Field(
        default=None, sa_column=sa.Column(_enum_type(FallbackReason, "fallback_reason"))
    )
    # The provider that answered, even when its text was refused.
    model_name: str | None = Field(default=None, sa_type=sa.Text)
    created_at: datetime = _created_at()


class Job(SQLModel, table=True):
    """Background work that is retried until it succeeds, such as a channel update."""

    __tablename__ = "jobs"  # type: ignore[assignment]
    __table_args__ = (
        sa.Index("ix_jobs_due", "status", "run_after"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    kind: JobKind = Field(sa_column=sa.Column(_enum_type(JobKind, "kind"), nullable=False))
    payload: dict[str, Any] = Field(sa_column=sa.Column(JSONB, nullable=False))
    status: JobStatus = Field(
        default=JobStatus.PENDING,
        sa_column=sa.Column(
            _enum_type(JobStatus, "status"), nullable=False, server_default=JobStatus.PENDING
        ),
    )
    attempts: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    max_attempts: int
    # A claimed job is pushed forward by a lease, so one whose runner died comes due again.
    run_after: datetime = Field(sa_type=sa.DateTime(timezone=True))  # pyright: ignore[reportArgumentType]
    last_error: str | None = Field(default=None, sa_type=sa.Text)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()
