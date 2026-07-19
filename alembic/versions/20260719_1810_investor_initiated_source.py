"""Add 'investor_initiated' to match_source — investors can now express
interest directly from the catalogue (e-commerce-style), not only on
AI/admin-created matches.

Revision ID: b7d2e4f8a133
Revises: a3f1c2d9e410
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d2e4f8a133"
down_revision: str | None = "a3f1c2d9e410"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE match_source ADD VALUE IF NOT EXISTS 'investor_initiated'")


def downgrade() -> None:
    # PostgreSQL cannot drop enum values; the extra value is harmless on rollback.
    pass
