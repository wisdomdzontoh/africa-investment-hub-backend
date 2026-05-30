"""Structured JSON logging configuration.

FastAPI logs to stdout as JSON, collected by Coolify and viewable in Grafana
(PRD §8.7). A request-id context var is injected so log lines can be correlated
across a single request.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from pythonjsonlogger import jsonlogger

from app.core.config import settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Attach the current request id (if any) to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def configure_logging() -> None:
    """Install a JSON formatter on the root logger.

    Idempotent: clears existing handlers so re-invocation (e.g. in tests or
    uvicorn reload) does not duplicate output.
    """
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
        timestamp=True,
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Align uvicorn/sqlalchemy loggers with our handler.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
