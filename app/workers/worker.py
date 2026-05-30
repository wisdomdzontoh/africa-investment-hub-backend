"""ARQ worker entrypoint (PRD §8.2, §15).

Run with:  arq app.workers.worker.WorkerSettings
Shares the same Docker image as the API; only the command differs.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import configure_logging, get_logger
from app.core.sentry import init_sentry
from app.workers.queue import get_redis_settings
from app.workers.tasks import (
    assess_project_risk,
    embed_consultant,
    embed_profile,
    embed_project,
    generate_consultant_matches,
    generate_matches,
    reindex_country,
)

logger = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    init_sentry()
    logger.info("ARQ worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("ARQ worker shutting down")


class WorkerSettings:
    functions = [
        embed_profile,
        embed_project,
        embed_consultant,
        generate_matches,
        generate_consultant_matches,
        assess_project_risk,
        reindex_country,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()
    max_jobs = 10
    job_timeout = 300
