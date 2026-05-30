"""Investor↔Project match model and pipeline (PRD §6.10, §10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import MatchSource, MatchStatus

if TYPE_CHECKING:
    from app.models.due_diligence import DueDiligenceRequest
    from app.models.investor import InvestorProfile
    from app.models.project import Project


class Match(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("investor_id", "project_id", name="uq_matches_investor_project"),
    )

    investor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investor_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )

    score: Mapped[float | None] = mapped_column(Float)  # 0.0–1.0 compatibility
    explanation: Mapped[str | None] = mapped_column(Text)  # AI-generated
    source: Mapped[MatchSource] = mapped_column(
        pg_enum(MatchSource, "match_source"), default=MatchSource.ai_generated, nullable=False
    )
    status: Mapped[MatchStatus] = mapped_column(
        pg_enum(MatchStatus, "match_status"),
        default=MatchStatus.ai_recommended,
        nullable=False,
        index=True,
    )
    # Investor identity withheld from project owner during confidential engagement.
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)

    investor_interest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Relationships ──
    investor: Mapped[InvestorProfile] = relationship(back_populates="matches")
    project: Mapped[Project] = relationship(back_populates="matches")
    due_diligence: Mapped[DueDiligenceRequest | None] = relationship(
        back_populates="match", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Match {self.id} status={self.status.value} score={self.score}>"
