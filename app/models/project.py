"""Project model (PRD §6.3, §10)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import embedding_column, pg_enum
from app.models.enums import FundingType, ProjectStage, ProjectStatus, RiskLevel

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.milestone import Milestone
    from app.models.user import User


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    # Composite indexes for the public catalogue: every listing query filters
    # on status, then sorts by one of these columns (PRD §6.1; BE-01).
    # Low-cardinality enum filters (stage, funding_type, risk) ride the status
    # index — dedicated b-trees on them would rarely be chosen by the planner.
    __table_args__ = (
        Index("ix_projects_status_created_at", "status", "created_at"),
        Index("ix_projects_status_funding_required", "status", "funding_required"),
        Index("ix_projects_status_expected_roi_max", "status", "expected_roi_max"),
        Index("ix_projects_status_view_count", "status", "view_count"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # ── Section A — Overview ──
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sector: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    brief_description: Mapped[str] = mapped_column(String(500), nullable=False)  # public card
    executive_summary: Mapped[str | None] = mapped_column(Text)  # approved investors
    full_description: Mapped[str | None] = mapped_column(Text)  # gated: NDA-signed only
    project_stage: Mapped[ProjectStage] = mapped_column(
        pg_enum(ProjectStage, "project_stage"), nullable=False
    )

    # ── Section B — Funding ──
    funding_required: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    funding_type: Mapped[FundingType] = mapped_column(
        pg_enum(FundingType, "funding_type"), nullable=False
    )
    min_investment: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    existing_funding: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    use_of_funds: Mapped[str | None] = mapped_column(Text)

    # ── Section C — Financials ──
    expected_roi_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    expected_roi_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    timeline_to_returns_months: Mapped[int | None] = mapped_column(Integer)
    projected_revenue_12m: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    projected_revenue_24m: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    projected_revenue_36m: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    current_annual_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))

    # ── Admin-controlled ──
    risk_level: Mapped[RiskLevel | None] = mapped_column(pg_enum(RiskLevel, "risk_level"))
    status: Mapped[ProjectStatus] = mapped_column(
        pg_enum(ProjectStatus, "project_status"),
        default=ProjectStatus.pending,
        nullable=False,
        index=True,
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    admin_notes: Mapped[str | None] = mapped_column(Text)  # internal only

    # ── AI / documents ──
    embedding: Mapped[list[float] | None] = mapped_column(embedding_column())
    documents: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    view_count: Mapped[int] = mapped_column(Integer, default=0)

    # ── Relationships ──
    owner: Mapped[User] = relationship(back_populates="projects")
    matches: Mapped[list[Match]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    milestones: Mapped[list[Milestone]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Project {self.id} {self.title!r} status={self.status.value}>"
