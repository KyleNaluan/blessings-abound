"""Add the synthetic sales history tables

Revision ID: dd3c26e18458
Revises: c0e0da5ee0c1
Create Date: 2026-11-05 17:28:19.201556+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd3c26e18458"
down_revision: str | Sequence[str] | None = "c0e0da5ee0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "synthetic_items",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("forwarded_on", sa.Date(), nullable=False),
        sa.Column(
            "store_department",
            sa.Enum(
                "clothing",
                "electronics_games",
                name="store_department",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
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
        sa.Column("typical_price_cents", sa.Integer(), nullable=False),
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
        sa.Column(
            "outcome",
            sa.Enum(
                "accepted",
                "rejected",
                name="outcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("overridden", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "category = 'apparel' OR department IS NULL",
            name=op.f("ck_synthetic_items_department_for_apparel_only"),
        ),
        sa.CheckConstraint(
            "overridden = ((recommendation = 'yes' AND outcome = 'rejected') "
            "OR (recommendation = 'no' AND outcome = 'accepted'))",
            name=op.f("ck_synthetic_items_overridden_against_recommendation"),
        ),
        sa.CheckConstraint(
            "typical_price_cents > 0", name=op.f("ck_synthetic_items_typical_price_cents_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synthetic_items")),
    )
    op.create_index(
        op.f("ix_synthetic_items_forwarded_on"), "synthetic_items", ["forwarded_on"], unique=False
    )
    op.create_table(
        "synthetic_listings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
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
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("listed_on", sa.Date(), nullable=False),
        sa.Column("sold_on", sa.Date(), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "(sold_on IS NULL) <> (ended_on IS NULL)",
            name=op.f("ck_synthetic_listings_sold_or_ended"),
        ),
        sa.CheckConstraint(
            "price_cents > 0", name=op.f("ck_synthetic_listings_price_cents_positive")
        ),
        sa.CheckConstraint(
            "sold_on >= listed_on AND ended_on > listed_on",
            name=op.f("ck_synthetic_listings_closed_after_listing"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["synthetic_items.id"],
            name=op.f("fk_synthetic_listings_item_id_synthetic_items"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synthetic_listings")),
        sa.UniqueConstraint(
            "item_id", "channel", name=op.f("uq_synthetic_listings_item_id_channel")
        ),
    )
    op.create_index(
        op.f("ix_synthetic_listings_listed_on"), "synthetic_listings", ["listed_on"], unique=False
    )
    op.create_index(
        op.f("ix_synthetic_listings_sold_on"), "synthetic_listings", ["sold_on"], unique=False
    )
    # Like every other table, so Supabase's automatic web API reads none of the history.
    for table in ("synthetic_items", "synthetic_listings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index(op.f("ix_synthetic_listings_sold_on"), table_name="synthetic_listings")
    op.drop_index(op.f("ix_synthetic_listings_listed_on"), table_name="synthetic_listings")
    op.drop_table("synthetic_listings")
    op.drop_index(op.f("ix_synthetic_items_forwarded_on"), table_name="synthetic_items")
    op.drop_table("synthetic_items")
