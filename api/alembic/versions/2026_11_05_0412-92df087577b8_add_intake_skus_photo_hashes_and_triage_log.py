"""Add intake SKUs, photo hashes and the triage log

Revision ID: 92df087577b8
Revises: a22142b97826
Create Date: 2026-11-05 04:12:05.687761+00:00

"""

import re
import unicodedata
from collections.abc import Sequence
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "92df087577b8"
down_revision: str | Sequence[str] | None = "a22142b97826"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STORE_DEPARTMENTS = ("clothing", "electronics_games")
OUTCOMES = ("accepted", "rejected")
DESTINATIONS = ("store_floor", "seasonal_storage", "discard_or_donate")
# Frozen copies of the store's time zone and the initials rule in app/intake.py on the day this
# ran, so a later change there can't change what this migration does.
STORE_TIMEZONE = ZoneInfo("America/Chicago")
# Two initials, the date as MMDDYY and a sequence of at least two digits.
SKU_PATTERN = "^[A-Z]{2}[0-9]{8,}$"


def _initials(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z]+", folded)
    if not words:
        return "XX"
    letters = (words[0] + "XX")[:2] if len(words) == 1 else words[0][0] + words[-1][0]
    return letters.upper()


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def _give_real_skus() -> None:
    """Replace each placeholder SKU from the walking skeleton with a real one.

    Each item gets its lister's initials and the store's date on the day it was taken in, numbered
    in the order the items were made after any real SKU with the same start, and the counts carry
    on from there for new intakes.
    """
    connection = op.get_bind()
    counts: dict[str, int] = {}
    # Real SKUs are only here after a downgrade and upgrade, and their numbers stay taken.
    real = connection.execute(
        sa.text("SELECT sku FROM items WHERE sku ~ :pattern"), {"pattern": SKU_PATTERN}
    ).scalars()
    for sku in real:
        counts[sku[:8]] = max(counts.get(sku[:8], 0), int(sku[8:]))
    placeholders = connection.execute(
        sa.text(
            "SELECT items.id, items.created_at, profiles.display_name FROM items "
            "JOIN profiles ON profiles.auth_user_id = items.lister_id "
            "WHERE items.sku LIKE 'PLACEHOLDER-%' ORDER BY items.created_at, items.id"
        )
    ).all()
    for item_id, created_at, display_name in placeholders:
        prefix = f"{_initials(display_name)}{created_at.astimezone(STORE_TIMEZONE):%m%d%y}"
        counts[prefix] = counts.get(prefix, 0) + 1
        connection.execute(
            sa.text("UPDATE items SET sku = :sku WHERE id = :id"),
            {"sku": f"{prefix}{counts[prefix]:02d}", "id": item_id},
        )
    for prefix, last_value in counts.items():
        connection.execute(
            sa.text("INSERT INTO sku_sequences (prefix, last_value) VALUES (:prefix, :last_value)"),
            {"prefix": prefix, "last_value": last_value},
        )


def upgrade() -> None:
    op.create_table(
        "sku_sequences",
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.CheckConstraint("last_value > 0", name=op.f("ck_sku_sequences_last_value_positive")),
        sa.PrimaryKeyConstraint("prefix", name=op.f("pk_sku_sequences")),
    )
    op.create_table(
        "triage_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=False),
        sa.Column("store_department", _enum("store_department", STORE_DEPARTMENTS), nullable=True),
        sa.Column("outcome", _enum("outcome", OUTCOMES), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("destination", _enum("destination", DESTINATIONS), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(outcome = 'rejected' AND rejection_reason IS NOT NULL AND destination IS NOT NULL) "
            "OR (outcome = 'accepted' AND rejection_reason IS NULL AND destination IS NULL)",
            name=op.f("ck_triage_log_rejection_has_reason_and_destination"),
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["decisions.id"], name=op.f("fk_triage_log_decision_id_decisions")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["items.id"], name=op.f("fk_triage_log_item_id_items")
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["profiles.auth_user_id"],
            name=op.f("fk_triage_log_submitted_by_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_triage_log")),
        sa.UniqueConstraint("decision_id", name=op.f("uq_triage_log_decision_id")),
    )
    op.create_index(op.f("ix_triage_log_item_id"), "triage_log", ["item_id"], unique=False)
    op.create_index(op.f("ix_triage_log_recorded_at"), "triage_log", ["recorded_at"], unique=False)
    op.create_index(
        op.f("ix_triage_log_submitted_by"), "triage_log", ["submitted_by"], unique=False
    )

    # Items taken in before this have no real hash, because their photos are in storage and not
    # here, so they start with none and the repeat photo guard never matches them.
    op.add_column(
        "items",
        sa.Column("photo_hashes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_items_photo_hashes_count"),
        "items",
        "cardinality(photo_hashes) IN (0, cardinality(photo_keys))",
    )
    op.drop_index(op.f("ix_items_photo_hash"), table_name="items")
    op.drop_column("items", "photo_hash")
    op.create_index(
        "ix_items_photo_hashes", "items", ["photo_hashes"], unique=False, postgresql_using="gin"
    )
    # Empty for the items taken in before intake asked for it.
    op.add_column("items", sa.Column("store_department", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        op.f("ck_items_store_department"), "items", _in("store_department", STORE_DEPARTMENTS)
    )

    _give_real_skus()

    for table in ("sku_sequences", "triage_log"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # The real SKUs stay, because the placeholders they replaced can't be told apart any more.
    op.drop_constraint(op.f("ck_items_store_department"), "items", type_="check")
    op.drop_column("items", "store_department")
    op.add_column("items", sa.Column("photo_hash", sa.Text(), nullable=True))
    op.execute("UPDATE items SET photo_hash = 'placeholder-' || replace(id::text, '-', '')")
    op.alter_column("items", "photo_hash", nullable=False)
    op.drop_index("ix_items_photo_hashes", table_name="items", postgresql_using="gin")
    op.create_index(op.f("ix_items_photo_hash"), "items", ["photo_hash"], unique=False)
    op.drop_constraint(op.f("ck_items_photo_hashes_count"), "items", type_="check")
    op.drop_column("items", "photo_hashes")
    op.drop_index(op.f("ix_triage_log_submitted_by"), table_name="triage_log")
    op.drop_index(op.f("ix_triage_log_recorded_at"), table_name="triage_log")
    op.drop_index(op.f("ix_triage_log_item_id"), table_name="triage_log")
    op.drop_table("triage_log")
    op.drop_table("sku_sequences")
