"""Consultant/partner profile and consultant-match models (PRD §6.11, §10)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ARRAY, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import embedding_column, pg_enum
from app.models.enums import ConsultantMatchStatus, ConsultantStatus, ContactPreference

if TYPE_CHECKING:
    from app.models.investor import InvestorProfile
    from app.models.project import Project
    from app.models.user import User


class ConsultantProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "consultant_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    city: Mapped[str | None] = mapped_column(String(128))
    expertise_areas: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    sectors_served: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    years_of_experience: Mapped[int | None] = mapped_column(Integer)
    languages_spoken: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    bio: Mapped[str | None] = mapped_column(Text)
    key_achievements: Mapped[str | None] = mapped_column(Text)
    contact_preference: Mapped[ContactPreference] = mapped_column(
        pg_enum(ContactPreference, "contact_preference"),
        default=ContactPreference.platform_message,
        nullable=False,
    )

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # admin badge
    status: Mapped[ConsultantStatus] = mapped_column(
        pg_enum(ConsultantStatus, "consultant_status"),
        default=ConsultantStatus.pending,
        nullable=False,
        index=True,
    )

    embedding: Mapped[list[float] | None] = mapped_column(embedding_column())
    documents: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # CV, portfolio

    user: Mapped[User] = relationship(back_populates="consultant_profile")
    consultant_matches: Mapped[list[ConsultantMatch]] = relationship(
        back_populates="consultant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConsultantProfile {self.id} {self.full_name!r}>"


class ConsultantMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "consultant_matches"

    investor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investor_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    consultant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consultant_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    score: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ConsultantMatchStatus] = mapped_column(
        pg_enum(ConsultantMatchStatus, "consultant_match_status"),
        default=ConsultantMatchStatus.recommended,
        nullable=False,
    )

    investor: Mapped[InvestorProfile] = relationship(back_populates="consultant_matches")
    consultant: Mapped[ConsultantProfile] = relationship(back_populates="consultant_matches")
    project: Mapped[Project | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConsultantMatch {self.id} status={self.status.value}>"
