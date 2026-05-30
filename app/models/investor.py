"""Investor profile model (PRD §6.2, §10)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import ARRAY, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import embedding_column, pg_enum
from app.models.enums import RiskLevel

if TYPE_CHECKING:
    from app.models.consultant import ConsultantMatch
    from app.models.match import Match
    from app.models.user import User


class InvestorProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "investor_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    # ── Section A — Company information ──
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_of_registration: Mapped[str] = mapped_column(String(2), nullable=False)
    # Sensitive: encrypted at rest (PRD §14).
    registration_number: Mapped[str | None] = mapped_column(EncryptedString(512))
    years_of_operation: Mapped[int | None] = mapped_column()
    registered_address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(512))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_title: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(64))

    # ── Section B — Investment profile ──
    investment_countries: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    investment_sectors: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    investment_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    min_ticket_size: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    max_ticket_size: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    preferred_deal_size: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    capital_availability: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))

    # ── Section C — Risk and returns ──
    risk_appetite: Mapped[RiskLevel | None] = mapped_column(pg_enum(RiskLevel, "risk_level"))
    target_roi_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    target_roi_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    time_horizon: Mapped[str | None] = mapped_column(String(128))
    preferred_ownership_structures: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    exit_strategy: Mapped[str | None] = mapped_column(String(255))
    preferred_ownership_pct_min: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    preferred_ownership_pct_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    # ── Section D — Compliance and ESG ──
    esg_requirements: Mapped[str | None] = mapped_column(Text)
    sectors_excluded: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    political_risk_tolerance: Mapped[str | None] = mapped_column(String(64))
    currency_risk_tolerance: Mapped[str | None] = mapped_column(String(64))

    # ── Section E — Track record ──
    previous_projects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    certifications: Mapped[str | None] = mapped_column(Text)

    # ── AI / documents ──
    embedding: Mapped[list[float] | None] = mapped_column(embedding_column())
    # [{type, r2_key, filename, uploaded_at, content_type, size}]
    documents: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    # ── Relationships ──
    user: Mapped[User] = relationship(back_populates="investor_profile")
    matches: Mapped[list[Match]] = relationship(
        back_populates="investor", cascade="all, delete-orphan"
    )
    consultant_matches: Mapped[list[ConsultantMatch]] = relationship(
        back_populates="investor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvestorProfile {self.id} {self.company_name!r}>"
