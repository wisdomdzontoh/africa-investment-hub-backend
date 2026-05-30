"""Sentry error tracking initialisation (PRD §8.7)."""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def init_sentry() -> None:
    """Initialise the Sentry SDK if a DSN is configured.

    No-op when ``SENTRY_DSN`` is empty (e.g. local dev / tests).
    """
    if not settings.SENTRY_DSN:
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        release=settings.APP_VERSION,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )
    logger.info("Sentry initialised for environment=%s", settings.ENVIRONMENT)
