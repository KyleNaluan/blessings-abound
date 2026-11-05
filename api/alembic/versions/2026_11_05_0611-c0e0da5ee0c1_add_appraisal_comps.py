"""Add the comps behind each appraisal

Revision ID: c0e0da5ee0c1
Revises: 92df087577b8
Create Date: 2026-11-05 06:11:40.560743+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c0e0da5ee0c1"
down_revision: str | Sequence[str] | None = "92df087577b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Appraisals made before this have no comps saved, so they show none.
    op.add_column(
        "appraisals",
        sa.Column(
            "comps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("appraisals", "comps")
