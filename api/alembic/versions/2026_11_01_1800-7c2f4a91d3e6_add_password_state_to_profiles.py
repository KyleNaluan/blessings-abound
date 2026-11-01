"""Add password state to profiles

Revision ID: 7c2f4a91d3e6
Revises: 140984f830d9
Create Date: 2026-11-01 18:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c2f4a91d3e6"
down_revision: str | Sequence[str] | None = "140984f830d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column("profiles", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "invited_at")
    op.drop_column("profiles", "must_change_password")
