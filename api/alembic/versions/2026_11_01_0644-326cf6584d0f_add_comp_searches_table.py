"""Add comp_searches table

Revision ID: 326cf6584d0f
Revises: 4a7ac07e1e4d
Create Date: 2026-11-01 06:44:53.783144+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "326cf6584d0f"
down_revision: str | Sequence[str] | None = "4a7ac07e1e4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comp_searches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("buying_format", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comp_searches")),
    )
    op.create_index(
        "ix_comp_searches_lookup",
        "comp_searches",
        ["engine", "query", "condition", "buying_format", "fetched_at"],
        unique=False,
    )
    # No policies, so Supabase's automatic web API cannot read the cache, see docs/database.md.
    op.execute("ALTER TABLE comp_searches ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_comp_searches_lookup", table_name="comp_searches")
    op.drop_table("comp_searches")
