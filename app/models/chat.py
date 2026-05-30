"""AI chat session model (PRD §12.1, §10)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    # Null for anonymous visitors; set once a logged-in user owns the session.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    session_token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # [{role, content, timestamp}]
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatSession {self.id} token={self.session_token[:8]}…>"
