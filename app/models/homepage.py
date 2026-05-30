"""Homepage CMS content (PRD §6.4, §10). Single-row table."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class HomepageContent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "homepage_content"

    # [{label: {en,fr,zh}, value: str}]
    stats: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{step, title: {en,fr,zh}, description: {en,fr,zh}}]
    process_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{sector, description: {en,fr,zh}, icon}]
    sector_highlights: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{name, logo_r2_key, url}] — not translated
    partner_logos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{name, title, photo_r2_key, bio: {en,fr,zh}}] — About page team
    team_members: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    advisory_board: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    editor: Mapped[User | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HomepageContent {self.id}>"
