"""Shared async Redis client.

A single connection pool is reused across rate limiting, JWKS caching, AI
response caching, and ARQ enqueue helpers.
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.core.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide Redis client (lazily initialised)."""
    global _redis
    if _redis is None:
        _redis = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
