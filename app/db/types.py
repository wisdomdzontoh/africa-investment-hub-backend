"""Reusable column types and helpers shared by models."""

from __future__ import annotations

import enum
from typing import TypeVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum as SAEnum

from app.core.config import settings

_E = TypeVar("_E", bound=enum.Enum)

# Embedding dimension for OpenAI text-embedding-3-small (PRD §8.4).
EMBEDDING_DIM = settings.EMBEDDING_DIM


def embedding_column() -> Vector:
    """A pgvector column sized for our embedding model."""
    return Vector(EMBEDDING_DIM)


def pg_enum(enum_cls: type[_E], name: str) -> SAEnum:
    """A native PostgreSQL enum that stores the Enum *value* (not the name).

    ``name`` is the Postgres type name; ``create_type=False`` lets Alembic own
    enum creation in migrations rather than implicitly on table create.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        native_enum=True,
        create_type=True,
    )
