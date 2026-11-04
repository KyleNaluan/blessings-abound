"""Add the settings table and seed it with the values the code used before

Revision ID: b4cdac51508b
Revises: b81d5e3c7a02
Create Date: 2026-11-04 01:41:43.179927+00:00

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4cdac51508b"
down_revision: str | Sequence[str] | None = "b81d5e3c7a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED: dict[str, dict[str, Any]] = {
    "box_sizes": {
        "boxes": [
            {"kind": "mailer", "length_in": 13.0, "width_in": 10.0, "height_in": None},
            {"kind": "mailer", "length_in": 15.5, "width_in": 12.0, "height_in": None},
            {"kind": "mailer", "length_in": 19.0, "width_in": 14.5, "height_in": None},
            {"kind": "box", "length_in": 8.0, "width_in": 6.0, "height_in": 4.0},
            {"kind": "box", "length_in": 10.0, "width_in": 8.0, "height_in": 6.0},
            {"kind": "box", "length_in": 12.0, "width_in": 12.0, "height_in": 6.0},
            {"kind": "box", "length_in": 16.0, "width_in": 12.0, "height_in": 8.0},
        ]
    },
    "seasonal_calendar": {
        "seasons": [
            {
                "name": "Halloween costumes",
                "category": "apparel",
                "match_words": ["costume", "halloween"],
                "months": [8, 9, 10],
            },
            {
                "name": "Holiday sweaters",
                "category": "apparel",
                "match_words": ["christmas", "ugly sweater", "holiday"],
                "months": [10, 11, 12],
            },
            {
                "name": "Football gear",
                "category": "apparel",
                "match_words": ["football", "nfl", "chiefs"],
                "months": [8, 9, 10, 11, 12, 1],
            },
            {
                "name": "Coats and jackets",
                "category": "apparel",
                "match_words": ["coat", "jacket", "parka", "puffer", "peacoat", "overcoat"],
                "months": [8, 9, 10, 11, 12, 1],
            },
            {
                "name": "Sweaters",
                "category": "apparel",
                "match_words": ["sweater", "cardigan", "turtleneck", "fleece"],
                "months": [9, 10, 11, 12, 1, 2],
            },
            {
                "name": "Boots",
                "category": "apparel",
                "match_words": ["boot"],
                "months": [9, 10, 11, 12, 1],
            },
            {
                "name": "Swimwear",
                "category": "apparel",
                "match_words": ["swimsuit", "swim", "bikini"],
                "months": [3, 4, 5, 6, 7],
            },
            {
                "name": "Shorts",
                "category": "apparel",
                "match_words": ["shorts"],
                "months": [3, 4, 5, 6, 7, 8],
            },
            {
                "name": "Sandals",
                "category": "apparel",
                "match_words": ["sandal", "flip flop"],
                "months": [3, 4, 5, 6, 7],
            },
        ]
    },
    "worth_listing": {"threshold_cents": 3000},
    "fees": {"fee_rate": 0.136, "per_order_fee_cents": 40, "supplies_cents": 150},
    "ask_to_sale": {"apparel": 0.645, "electronics_games": 0.94},
    "shipping_weight": {
        "ounce_tiers_oz": [4.0, 8.0, 12.0, 15.999],
        "max_weight_oz": 1120,
        "max_length_plus_girth_in": 130.0,
        "dim_weight_min_cubic_in": 1728,
        "dim_weight_divisor": 139,
    },
}


def upgrade() -> None:
    settings = op.create_table(
        "settings",
        sa.Column(
            "key",
            sa.Enum(
                "box_sizes",
                "seasonal_calendar",
                "worth_listing",
                "fees",
                "ask_to_sale",
                "shipping_weight",
                name="key",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["profiles.auth_user_id"], name=op.f("fk_settings_updated_by_profiles")
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.execute("ALTER TABLE settings ENABLE ROW LEVEL SECURITY")
    assert settings is not None
    # A frozen copy of the defaults in app/store_settings.py on the day this ran, so a later change
    # to a default does not rewrite this history. docs/settings.md gives the source for each value.
    op.bulk_insert(settings, [{"key": key, "value": value} for key, value in SEED.items()])


def downgrade() -> None:
    op.drop_table("settings")
