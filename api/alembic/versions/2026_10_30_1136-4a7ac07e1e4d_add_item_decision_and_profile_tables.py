"""Add item, decision and profile tables, with row-level security on every table.

Revision ID: 4a7ac07e1e4d
Revises: 90b9c1f65e5c
Create Date: 2026-10-30 11:36:18.682289+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a7ac07e1e4d"
down_revision: str | Sequence[str] | None = "90b9c1f65e5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Row-level security with no policies blocks Supabase's automatic web API, while the API still gets
# through because it connects as the owner of these tables. alembic_version is here because it
# sits in the same public schema.
RLS_TABLES = ("profiles", "items", "item_cards", "appraisals", "decisions", "alembic_version")


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("auth_user_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "staff",
                "manager",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="staff",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint("username ~ '^[a-z0-9._-]+$'", name=op.f("ck_profiles_username_format")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_profiles_email_lowercase")),
        sa.PrimaryKeyConstraint("auth_user_id", name=op.f("pk_profiles")),
        sa.UniqueConstraint("email", name=op.f("uq_profiles_email")),
        sa.UniqueConstraint("username", name=op.f("uq_profiles_username")),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("lister_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "intake",
                "card_ready",
                "appraised",
                "declined",
                "approved",
                "held_for_season",
                "listed",
                "sold",
                "picked",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="intake",
            nullable=False,
        ),
        sa.Column("photo_keys", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("photo_hash", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "cardinality(photo_keys) BETWEEN 1 AND 4", name=op.f("ck_items_photo_keys_count")
        ),
        sa.ForeignKeyConstraint(
            ["lister_id"], ["profiles.auth_user_id"], name=op.f("fk_items_lister_id_profiles")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
        sa.UniqueConstraint("sku", name=op.f("uq_items_sku")),
    )
    op.create_index(op.f("ix_items_lister_id"), "items", ["lister_id"], unique=False)
    op.create_index(op.f("ix_items_photo_hash"), "items", ["photo_hash"], unique=False)
    op.create_table(
        "appraisals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("price_low_cents", sa.Integer(), nullable=True),
        sa.Column("price_typical_cents", sa.Integer(), nullable=True),
        sa.Column("price_high_cents", sa.Integer(), nullable=True),
        sa.Column("net_after_fees_cents", sa.Integer(), nullable=True),
        sa.Column("comps_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "confidence",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="confidence",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "recommendation",
            sa.Enum(
                "yes",
                "no",
                "check",
                name="recommendation",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("rules_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("comps_count >= 0", name=op.f("ck_appraisals_comps_count_non_negative")),
        sa.CheckConstraint(
            "price_high_cents >= 0", name=op.f("ck_appraisals_price_high_cents_non_negative")
        ),
        sa.CheckConstraint(
            "price_low_cents <= price_typical_cents AND price_typical_cents <= price_high_cents",
            name=op.f("ck_appraisals_price_range_ordered"),
        ),
        sa.CheckConstraint(
            "price_low_cents >= 0", name=op.f("ck_appraisals_price_low_cents_non_negative")
        ),
        sa.CheckConstraint(
            "price_typical_cents >= 0", name=op.f("ck_appraisals_price_typical_cents_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_appraisals_item_id_items")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appraisals")),
        sa.UniqueConstraint("id", "item_id", name=op.f("uq_appraisals_id_item_id")),
    )
    op.create_index(op.f("ix_appraisals_item_id"), "appraisals", ["item_id"], unique=False)
    op.create_table(
        "item_cards",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "apparel",
                "electronics_games",
                name="category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("visible_text", sa.Text(), nullable=True),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column(
            "model_confidence",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="model_confidence",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "condition",
            sa.Enum(
                "new_with_tags",
                "new_without_tags",
                "pre_owned",
                name="condition",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "department",
            sa.Enum(
                "mens",
                "womens",
                "kids",
                name="department",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("size", sa.Text(), nullable=True),
        sa.Column("size_type", sa.Text(), nullable=True),
        sa.Column("flaws", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("tested_working", sa.Boolean(), nullable=True),
        sa.Column("complete_in_box", sa.Boolean(), nullable=True),
        sa.Column("accessories_included", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("material", sa.Text(), nullable=True),
        sa.Column("exact_model", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("staff_edited", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint(
            "flaws <@ ARRAY['stains', 'tears', 'scuffs', 'missing_parts']::text[]",
            name=op.f("ck_item_cards_flaws_known"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_item_cards_item_id_items")
        ),
        sa.PrimaryKeyConstraint("item_id", name=op.f("pk_item_cards")),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("appraisal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "yes",
                "no",
                name="decision",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["appraisal_id", "item_id"],
            ["appraisals.id", "appraisals.item_id"],
            name=op.f("fk_decisions_appraisal_id_item_id_appraisals"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["profiles.auth_user_id"], name=op.f("fk_decisions_decided_by_profiles")
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], name=op.f("fk_decisions_item_id_items")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisions")),
    )
    op.create_index(op.f("ix_decisions_decided_at"), "decisions", ["decided_at"], unique=False)
    op.create_index(op.f("ix_decisions_decided_by"), "decisions", ["decided_by"], unique=False)
    op.create_index(op.f("ix_decisions_item_id"), "decisions", ["item_id"], unique=False)
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE alembic_version DISABLE ROW LEVEL SECURITY")
    op.drop_index(op.f("ix_decisions_item_id"), table_name="decisions")
    op.drop_index(op.f("ix_decisions_decided_by"), table_name="decisions")
    op.drop_index(op.f("ix_decisions_decided_at"), table_name="decisions")
    op.drop_table("decisions")
    op.drop_table("item_cards")
    op.drop_index(op.f("ix_appraisals_item_id"), table_name="appraisals")
    op.drop_table("appraisals")
    op.drop_index(op.f("ix_items_photo_hash"), table_name="items")
    op.drop_index(op.f("ix_items_lister_id"), table_name="items")
    op.drop_table("items")
    op.drop_table("profiles")
