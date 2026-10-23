"""Baseline: the empty schema that every later migration builds on.

Revision ID: 90b9c1f65e5c
Revises:
Create Date: 2026-10-23 21:56:46.901434+00:00

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "90b9c1f65e5c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
