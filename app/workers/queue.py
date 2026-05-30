"""ARQ enqueue helper.

A small wrapper so services can enqueue background jobs (PRD §8.2 task queue)
without each one managing an ARQ pool. Jobs are referenced by name; the worker
(``app.workers.worker``) registers the matching coroutines.

Enqueueing is best-effort: if Redis/ARQ is unavailable we log and continue so
the user-facing request still succeeds (the job can be re-triggered).
"""

from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_settings = RedisSettings(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    database=settings.REDIS_DB,
    password=settings.REDIS_PASSWORD or None,
)


def get_redis_settings() -> RedisSettings:
    return _redis_settings


async def enqueue(job_name: str, *args: Any, **kwargs: Any) -> None:
    """Enqueue an ARQ job by name. Swallows connection errors (logged)."""
    try:
        pool = await create_pool(_redis_settings)
        try:
            await pool.enqueue_job(job_name, *args, **kwargs)
        finally:
            await pool.aclose()
    except Exception:  # noqa: BLE001 - never break the request path on queue errors
        logger.exception("Failed to enqueue job %s", job_name)
