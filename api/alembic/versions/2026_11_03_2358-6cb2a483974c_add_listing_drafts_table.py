"""Add the listing drafts table

Revision ID: 6cb2a483974c
Revises: b81d5e3c7a02
Create Date: 2026-11-03 23:58:13.241898+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6cb2a483974c"
down_revision: str | Sequence[str] | None = "b81d5e3c7a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_drafts",
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
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "draft",
                "awaiting_approval",
                name="state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "model",
                "template",
                name="source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "fallback_reason",
            sa.Enum(
                "flagged",
                "model_failed",
                "not_configured",
                name="fallback_reason",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("model_draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "model_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("staff_edited", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
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
            "(source = 'model') = (fallback_reason IS NULL)",
            name=op.f("ck_listing_drafts_fallback_reason_with_template"),
        ),
        sa.CheckConstraint(
            "state = 'draft' OR (submitted_at IS NOT NULL AND submitted_by IS NOT NULL)",
            name=op.f("ck_listing_drafts_submitted_after_draft"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["profiles.auth_user_id"],
            name=op.f("fk_listing_drafts_created_by_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_listing_drafts_item_id_items")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["profiles.auth_user_id"],
            name=op.f("fk_listing_drafts_submitted_by_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing_drafts")),
        sa.UniqueConstraint("item_id", "channel", name=op.f("uq_listing_drafts_item_id_channel")),
    )
    op.execute("ALTER TABLE listing_drafts ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("listing_drafts")
