"""User model — the application-side extension of a Clerk identity (PRD §10)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import Locale, UserRole, UserStatus

if TYPE_CHECKING:
    from app.models.consultant import ConsultantProfile
    from app.models.investor import InvestorProfile
    from app.models.notification import Notification
    from app.models.project import Project


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    clerk_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), default=UserRole.investor, nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), default=UserStatus.pending, nullable=False
    )
    locale: Mapped[Locale] = mapped_column(
        pg_enum(Locale, "locale"), default=Locale.en, nullable=False
    )

    # GDPR soft-delete (PRD §14). Hard-deleted by a scheduled task after 30 days.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # ── Relationships ──
    investor_profile: Mapped[InvestorProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    consultant_profile: Mapped[ConsultantProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    projects: Mapped[list[Project]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} role={self.role.value} status={self.status.value}>"
