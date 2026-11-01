"""Add staff_confirmed to item cards

Revision ID: 140984f830d9
Revises: 326cf6584d0f
Create Date: 2026-11-01 07:46:32.276454+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "140984f830d9"
down_revision: str | Sequence[str] | None = "326cf6584d0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "item_cards",
        sa.Column("staff_confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("item_cards", "staff_confirmed")
