"""Add the not listed online item status

Revision ID: a1524bfaaed5
Revises: dd3c26e18458
Create Date: 2026-11-06 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1524bfaaed5"
down_revision: str | Sequence[str] | None = "dd3c26e18458"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = (
    "intake",
    "card_ready",
    "appraised",
    "declined",
    "approved",
    "held_for_season",
    "listed",
    "sold",
    "picked",
)
NEW_STATUSES = (*OLD_STATUSES, "not_listed_online")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _swap_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def upgrade() -> None:
    _swap_check("items", "status", _in("status", NEW_STATUSES))


def downgrade() -> None:
    # An item taken out of online selling is declined, the nearest status the old code knew, and
    # the decision that took it out stays in decisions.
    op.execute(sa.text("UPDATE items SET status = 'declined' WHERE status = 'not_listed_online'"))
    _swap_check("items", "status", _in("status", OLD_STATUSES))
