"""Add listings, sale events, sync log, jobs and the mock channel schemas

Revision ID: 75f72c57bf2c
Revises: b81d5e3c7a02
Create Date: 2026-11-03 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "75f72c57bf2c"
down_revision: str | Sequence[str] | None = "b81d5e3c7a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APP_TABLES = ("jobs", "listings", "sale_events", "sync_log")
CHANNELS = ("channel_a", "channel_b")


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "publish_listing",
                "end_listing",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "done",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_jobs_attempts_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_due", "jobs", ["status", "run_after"], unique=False)
    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum(
                "channel_a",
                "channel_b",
                name="channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("channel_listing_id", sa.Text(), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "active",
                "sold",
                "ended",
                "rejected",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("price_cents > 0", name=op.f("ck_listings_price_cents_positive")),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["profiles.auth_user_id"],
            name=op.f("fk_listings_approved_by_profiles"),
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], name=op.f("fk_listings_item_id_items")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listings")),
        sa.UniqueConstraint(
            "channel", "channel_listing_id", name=op.f("uq_listings_channel_channel_listing_id")
        ),
        sa.UniqueConstraint("item_id", "channel", name=op.f("uq_listings_item_id_channel")),
    )
    op.create_index(op.f("ix_listings_approved_by"), "listings", ["approved_by"], unique=False)
    op.create_index(op.f("ix_listings_item_id"), "listings", ["item_id"], unique=False)
    op.create_table(
        "sale_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum(
                "channel_a",
                "channel_b",
                name="channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("channel_order_id", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "webhook",
                "polling",
                name="source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "price_cents >= 0", name=op.f("ck_sale_events_price_cents_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_sale_events_item_id_items")
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["listings.id"], name=op.f("fk_sale_events_listing_id_listings")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_events")),
        sa.UniqueConstraint(
            "channel", "channel_order_id", name=op.f("uq_sale_events_channel_channel_order_id")
        ),
    )
    op.create_index(op.f("ix_sale_events_item_id"), "sale_events", ["item_id"], unique=False)
    op.create_index(op.f("ix_sale_events_listing_id"), "sale_events", ["listing_id"], unique=False)
    op.create_table(
        "sync_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "event",
            sa.Enum(
                "published",
                "publish_rejected",
                "publish_failed",
                "publish_gave_up",
                "publish_skipped",
                "sale_recorded",
                "delisted",
                "delist_failed",
                "delist_gave_up",
                "delist_found_sold",
                "flagged",
                name="event",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Enum(
                "channel_a",
                "channel_b",
                name="channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("channel_listing_id", sa.Text(), nullable=True),
        sa.Column("channel_order_id", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "webhook",
                "polling",
                name="source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conflict",
            sa.Enum(
                "double_sale",
                "stale_listing",
                "unknown_listing",
                name="conflict",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("conflict_key", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(event = 'flagged') = (conflict IS NOT NULL) "
            "AND (conflict IS NULL) = (conflict_key IS NULL)",
            name=op.f("ck_sync_log_flag_has_conflict"),
        ),
        sa.CheckConstraint(
            "conflict IS NOT NULL OR (resolved_at IS NULL AND resolved_by IS NULL "
            "AND resolution IS NULL)",
            name=op.f("ck_sync_log_only_flags_resolve"),
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], name=op.f("fk_sync_log_item_id_items")),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["listings.id"], name=op.f("fk_sync_log_listing_id_listings")
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["profiles.auth_user_id"],
            name=op.f("fk_sync_log_resolved_by_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_log")),
    )
    op.create_index(op.f("ix_sync_log_created_at"), "sync_log", ["created_at"], unique=False)
    op.create_index(op.f("ix_sync_log_item_id"), "sync_log", ["item_id"], unique=False)
    op.create_index(op.f("ix_sync_log_listing_id"), "sync_log", ["listing_id"], unique=False)
    op.create_index(
        "uq_sync_log_open_conflict_key",
        "sync_log",
        ["conflict_key"],
        unique=True,
        postgresql_where=sa.text("conflict_key IS NOT NULL AND resolved_at IS NULL"),
    )
    for table in APP_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    for schema in CHANNELS:
        _create_channel(schema)


def _create_channel(schema: str) -> None:
    """One mock channel's schema and tables, reachable only by the channel's own role."""
    # The role starts with no login, and app/channel_roles.py gives it a password, which keeps
    # every password out of the repo.
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{schema}') "
        f"THEN CREATE ROLE {schema} NOLOGIN; END IF; END $$"
    )
    op.execute(f"CREATE SCHEMA {schema}")
    op.execute(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC")
    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("size", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column(
            "specifics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'sold', 'ended')", name=op.f("ck_listings_status")
        ),
        sa.CheckConstraint("price_cents > 0", name=op.f("ck_listings_price_cents_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listings")),
        sa.UniqueConstraint("external_ref", name=op.f("uq_listings_external_ref")),
        schema=schema,
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="paid", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('paid')", name=op.f("ck_orders_status")),
        sa.CheckConstraint("price_cents > 0", name=op.f("ck_orders_price_cents_positive")),
        sa.ForeignKeyConstraint(
            ["listing_id"], [f"{schema}.listings.id"], name=op.f("fk_orders_listing_id_listings")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        schema=schema,
    )
    op.create_index(
        op.f("ix_orders_listing_id"), "orders", ["listing_id"], unique=False, schema=schema
    )
    op.create_index(
        "uq_orders_one_paid_order_per_listing",
        "orders",
        ["listing_id"],
        unique=True,
        schema=schema,
        postgresql_where=sa.text("status = 'paid'"),
    )
    op.create_table(
        "controls",
        sa.Column("id", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("offline", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint("id", name=op.f("ck_controls_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_controls")),
        schema=schema,
    )
    op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {schema}")
    for table in ("listings", "orders", "controls"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.{table} TO {schema}")
        # Row-level security keeps every other role out even if a grant is added by mistake, and
        # the policy lets the channel's own role in.
        op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {schema}_only ON {schema}.{table} FOR ALL TO {schema} "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    for schema in reversed(CHANNELS):
        op.execute(f"DROP SCHEMA {schema} CASCADE")
        # DROP OWNED removes the role's grants elsewhere, such as on the database itself.
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{schema}') "
            f"THEN DROP OWNED BY {schema}; DROP ROLE {schema}; END IF; END $$"
        )
    op.drop_index(
        "uq_sync_log_open_conflict_key",
        table_name="sync_log",
        postgresql_where=sa.text("conflict_key IS NOT NULL AND resolved_at IS NULL"),
    )
    op.drop_index(op.f("ix_sync_log_listing_id"), table_name="sync_log")
    op.drop_index(op.f("ix_sync_log_item_id"), table_name="sync_log")
    op.drop_index(op.f("ix_sync_log_created_at"), table_name="sync_log")
    op.drop_table("sync_log")
    op.drop_index(op.f("ix_sale_events_listing_id"), table_name="sale_events")
    op.drop_index(op.f("ix_sale_events_item_id"), table_name="sale_events")
    op.drop_table("sale_events")
    op.drop_index(op.f("ix_listings_item_id"), table_name="listings")
    op.drop_index(op.f("ix_listings_approved_by"), table_name="listings")
    op.drop_table("listings")
    op.drop_index("ix_jobs_due", table_name="jobs")
    op.drop_table("jobs")
