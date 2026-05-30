"""RAG knowledge base chunks (PRD §12.1).

Embedded, queryable chunks of country regulatory content, FAQ, sector guides,
project summaries, and platform docs. Populated/refreshed by an ARQ reindex
job. Retrieval is via pgvector cosine distance.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import embedding_column, pg_enum
from app.models.enums import KnowledgeContentType


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_content_type_section", "content_type", "section"),
    )

    content_type: Mapped[KnowledgeContentType] = mapped_column(
        pg_enum(KnowledgeContentType, "knowledge_content_type"), nullable=False
    )
    # Provenance so a chunk can be re-derived / invalidated on source update.
    source_type: Mapped[str | None] = mapped_column(String(64))  # e.g. country_content
    source_id: Mapped[uuid.UUID | None] = mapped_column()
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    section: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(embedding_column())
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<KnowledgeChunk {self.id} type={self.content_type.value}>"
