"""Due diligence request model (PRD §6.8, §10) — Phase 2 entity."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import DueDiligenceStatus

if TYPE_CHECKING:
    from app.models.match import Match


class DueDiligenceRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "due_diligence_requests"

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    assigned_advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # [{item_id, category, title, status, document_r2_key, signed_off_by, signed_off_at}]
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[DueDiligenceStatus] = mapped_column(
        pg_enum(DueDiligenceStatus, "due_diligence_status"),
        default=DueDiligenceStatus.requested,
        nullable=False,
    )
    report_r2_key: Mapped[str | None] = mapped_column(String(512))  # generated PDF

    match: Mapped[Match] = relationship(back_populates="due_diligence")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DueDiligenceRequest {self.id} status={self.status.value}>"
