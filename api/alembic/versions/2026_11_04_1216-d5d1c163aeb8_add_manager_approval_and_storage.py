"""Add manager approval, the package and shelf for storage, and the Channel B fees

Revision ID: d5d1c163aeb8
Revises: b4cdac51508b
Create Date: 2026-11-04 12:16:04.130205+00:00

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5d1c163aeb8"
down_revision: str | Sequence[str] | None = "b4cdac51508b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATES = ("draft", "awaiting_approval")
NEW_STATES = (*OLD_STATES, "approved", "rejected")
OLD_KEYS = (
    "box_sizes",
    "seasonal_calendar",
    "worth_listing",
    "fees",
    "ask_to_sale",
    "shipping_weight",
)
NEW_KEYS = (*OLD_KEYS, "channel_b_fees")

# A frozen copy of the Channel B default in app/store_settings.py on the day this ran.
# docs/settings.md gives the source for each value.
SEED: dict[str, dict[str, Any]] = {
    "channel_b_fees": {
        "fee_rate": 0.2,
        "small_sale_fee_cents": 295,
        "small_sale_below_cents": 1500,
        "supplies_cents": 150,
    },
}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    op.add_column("items", sa.Column("release_month", sa.Date(), nullable=True))
    op.add_column("items", sa.Column("package_weight_oz", sa.Float(), nullable=True))
    op.add_column("items", sa.Column("box_code", sa.Text(), nullable=True))
    op.add_column("items", sa.Column("location_code", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_items_release_month_first_day"), "items", "EXTRACT(DAY FROM release_month) = 1"
    )
    op.create_check_constraint(
        op.f("ck_items_package_weight_oz_positive"), "items", "package_weight_oz > 0"
    )
    op.create_check_constraint(
        op.f("ck_items_package_weight_with_box"),
        "items",
        "(package_weight_oz IS NULL) = (box_code IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_items_location_after_package"),
        "items",
        "location_code IS NULL OR box_code IS NOT NULL",
    )

    op.add_column("listing_drafts", sa.Column("price_override_cents", sa.Integer(), nullable=True))
    op.add_column("listing_drafts", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column(
        "listing_drafts", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_listing_drafts_reviewed_by_profiles"),
        "listing_drafts",
        "profiles",
        ["reviewed_by"],
        ["auth_user_id"],
    )
    _swap_check("listing_drafts", "state", _in("state", NEW_STATES))
    op.create_check_constraint(
        op.f("ck_listing_drafts_reviewed_after_approval"),
        "listing_drafts",
        "(state IN ('approved', 'rejected')) = "
        "(reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_listing_drafts_price_override_cents_positive"),
        "listing_drafts",
        "price_override_cents > 0",
    )

    _swap_check("settings", "key", _in("key", NEW_KEYS))
    settings = sa.table(
        "settings", sa.column("key", sa.String), sa.column("value", postgresql.JSONB)
    )
    op.bulk_insert(settings, [{"key": key, "value": value} for key, value in SEED.items()])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'channel_b_fees'"))
    _swap_check("settings", "key", _in("key", OLD_KEYS))

    op.drop_constraint(
        op.f("ck_listing_drafts_price_override_cents_positive"), "listing_drafts", type_="check"
    )
    op.drop_constraint(
        op.f("ck_listing_drafts_reviewed_after_approval"), "listing_drafts", type_="check"
    )
    # Approved and rejected listings go back to waiting, which is the last state the old code knew.
    op.execute(
        sa.text(
            "UPDATE listing_drafts SET state = 'awaiting_approval' "
            "WHERE state IN ('approved', 'rejected')"
        )
    )
    _swap_check("listing_drafts", "state", _in("state", OLD_STATES))
    op.drop_constraint(
        op.f("fk_listing_drafts_reviewed_by_profiles"), "listing_drafts", type_="foreignkey"
    )
    op.drop_column("listing_drafts", "reviewed_at")
    op.drop_column("listing_drafts", "reviewed_by")
    op.drop_column("listing_drafts", "price_override_cents")

    op.drop_constraint(op.f("ck_items_location_after_package"), "items", type_="check")
    op.drop_constraint(op.f("ck_items_package_weight_with_box"), "items", type_="check")
    op.drop_constraint(op.f("ck_items_package_weight_oz_positive"), "items", type_="check")
    op.drop_constraint(op.f("ck_items_release_month_first_day"), "items", type_="check")
    op.drop_column("items", "location_code")
    op.drop_column("items", "box_code")
    op.drop_column("items", "package_weight_oz")
    op.drop_column("items", "release_month")
