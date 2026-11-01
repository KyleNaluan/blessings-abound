"""Add sign-in attempts and the time a temporary password was issued

Revision ID: b81d5e3c7a02
Revises: 7c2f4a91d3e6
Create Date: 2026-11-01 20:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b81d5e3c7a02"
down_revision: str | Sequence[str] | None = "7c2f4a91d3e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("temporary_password_issued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "sign_in_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username_hash", sa.Text(), nullable=False),
        sa.Column(
            "attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sign_in_attempts")),
    )
    op.create_index(
        op.f("ix_sign_in_attempts_attempted_at"), "sign_in_attempts", ["attempted_at"], unique=False
    )
    op.create_index(
        "ix_sign_in_attempts_lookup",
        "sign_in_attempts",
        ["username_hash", "attempted_at"],
        unique=False,
    )
    op.execute("ALTER TABLE sign_in_attempts ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_sign_in_attempts_lookup", table_name="sign_in_attempts")
    op.drop_index(op.f("ix_sign_in_attempts_attempted_at"), table_name="sign_in_attempts")
    op.drop_table("sign_in_attempts")
    op.drop_column("profiles", "temporary_password_issued_at")
