"""ARQ worker entrypoint (PRD §8.2, §15).

Run with:  arq app.workers.worker.WorkerSettings
Shares the same Docker image as the API; only the command differs.
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron

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
    notify_matching_investors,
    purge_deleted_users,
    reconcile_clerk_users,
    reindex_country,
    send_templated_email,
)

logger = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    init_sentry()
    logger.info("ARQ worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("ARQ worker shutting down")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        embed_profile,
        embed_project,
        embed_consultant,
        generate_matches,
        generate_consultant_matches,
        assess_project_risk,
        reindex_country,
        send_templated_email,
        notify_matching_investors,
    ]
    # Scheduled maintenance (PRD §14): GDPR purge after the 30-day window and
    # the Clerk-DB reconciliation backstop. Nightly, inside the low-traffic
    # window (PRD §7 plans Sundays 02:00-04:00 UTC for maintenance; these are
    # cheap enough to run daily).
    cron_jobs: ClassVar[list[Any]] = [
        cron(purge_deleted_users, hour=3, minute=10, run_at_startup=False),
        cron(reconcile_clerk_users, hour=3, minute=40, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()
    max_jobs = 10
    job_timeout = 300
