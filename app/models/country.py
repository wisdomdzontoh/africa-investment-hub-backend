"""Country regulatory CMS content and version history (PRD §6.4, §10).

Translatable text fields are stored as JSONB with locale keys
``{en, fr, zh}``; the API returns only the requested locale (falling back to
``en``). Phase 1 populates only ``en``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class CountryContent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "country_content"

    country_code: Mapped[str] = mapped_column(String(2), unique=True, index=True, nullable=False)
    country_name: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), index=True)

    # Localised rich-text sections: {en, fr, zh}
    investment_climate: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    investment_laws: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tax_system: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    business_registration: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    licensing_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    foreign_ownership_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    repatriation_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    immigration_requirements: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Not translated.
    key_contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    recent_news: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    editor: Mapped[User | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CountryContent {self.country_code} published={self.is_published}>"


class CountryContentVersion(UUIDPrimaryKeyMixin, Base):
    """Snapshot for version history — last 5 retained per country (PRD §6.4)."""

    __tablename__ = "country_content_versions"

    country_code: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CountryContentVersion {self.country_code} @ {self.created_at}>"
