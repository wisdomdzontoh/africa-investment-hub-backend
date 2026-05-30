"""Project milestone model — monitoring dashboard (PRD §6.6, §10), Phase 2."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import MilestoneStatus

if TYPE_CHECKING:
    from app.models.project import Project


class Milestone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "milestones"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    match_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("matches.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[MilestoneStatus] = mapped_column(
        pg_enum(MilestoneStatus, "milestone_status"),
        default=MilestoneStatus.pending,
        nullable=False,
    )
    evidence_r2_key: Mapped[str | None] = mapped_column(String(512))

    project: Mapped[Project] = relationship(back_populates="milestones")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Milestone {self.id} {self.title!r} status={self.status.value}>"
