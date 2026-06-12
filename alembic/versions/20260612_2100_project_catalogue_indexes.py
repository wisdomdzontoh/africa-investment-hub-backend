"""Composite indexes for the public project catalogue (BE-01).

Every public listing query filters on status and sorts by created_at,
funding_required, expected_roi_max, or view_count.

Revision ID: a3f1c2d9e410
Revises: 881ba76546b8
Create Date: 2026-06-12 21:00:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f1c2d9e410"
down_revision: str | None = "881ba76546b8"
branch_labels: str | None = None
depends_on: str | None = None

_INDEXES = (
    ("ix_projects_status_created_at", ["status", "created_at"]),
    ("ix_projects_status_funding_required", ["status", "funding_required"]),
    ("ix_projects_status_expected_roi_max", ["status", "expected_roi_max"]),
    ("ix_projects_status_view_count", ["status", "view_count"]),
)


def upgrade() -> None:
    for name, cols in _INDEXES:
        op.create_index(name, "projects", cols, unique=False)


def downgrade() -> None:
    for name, _ in _INDEXES:
        op.drop_index(name, table_name="projects")
