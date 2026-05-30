"""ARQ background tasks (PRD §8.2, §12).

Each task opens its own DB session (workers run outside the request lifecycle).
Tasks are registered on ``WorkerSettings.functions`` in ``worker.py``; the
function ``__name__`` is the job name used by ``enqueue(...)``.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.ai import embeddings, matching, risk
from app.services.knowledge_service import reindex_country_content

logger = get_logger(__name__)


async def embed_profile(ctx: dict[str, Any], investor_id: str) -> None:
    async with SessionLocal() as db:
        await embeddings.embed_investor(db, investor_id)  # type: ignore[arg-type]
        await db.commit()


async def embed_project(ctx: dict[str, Any], project_id: str) -> None:
    async with SessionLocal() as db:
        await embeddings.embed_project(db, project_id)  # type: ignore[arg-type]
        await db.commit()


async def embed_consultant(ctx: dict[str, Any], consultant_id: str) -> None:
    async with SessionLocal() as db:
        await embeddings.embed_consultant(db, consultant_id)  # type: ignore[arg-type]
        await db.commit()


async def generate_matches(ctx: dict[str, Any], investor_id: str) -> int:
    import uuid

    async with SessionLocal() as db:
        count = await matching.generate_project_matches(db, uuid.UUID(investor_id))
        await db.commit()
        logger.info("Generated %d matches for investor %s", count, investor_id)
        return count


async def generate_consultant_matches(
    ctx: dict[str, Any], investor_id: str, project_id: str | None = None
) -> int:
    import uuid

    async with SessionLocal() as db:
        count = await matching.generate_consultant_matches(
            db,
            investor_id=uuid.UUID(investor_id),
            project_id=uuid.UUID(project_id) if project_id else None,
        )
        await db.commit()
        return count


async def assess_project_risk(ctx: dict[str, Any], project_id: str) -> None:
    import uuid

    async with SessionLocal() as db:
        await risk.assess(db, uuid.UUID(project_id))
        await db.commit()


async def reindex_country(ctx: dict[str, Any], country_code: str) -> int:
    async with SessionLocal() as db:
        count = await reindex_country_content(db, country_code)
        await db.commit()
        return count
