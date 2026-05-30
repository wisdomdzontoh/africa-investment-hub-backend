"""Redis-backed rate limiting (PRD §14).

A fixed-window counter per (scope, identity) keyed in Redis. Tiers:
  - public endpoints: 30 req/min per IP
  - auth-sensitive endpoints: 10 req/min per IP (brute-force protection)
  - AI endpoints: 20 req/min per user

Applied as a router/route dependency rather than a global middleware so each
group gets the right tier and identity (IP vs. authenticated user).
"""

from __future__ import annotations

from enum import Enum

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.core.redis import get_redis


class RateTier(str, Enum):
    public = "public"
    auth = "auth"
    ai = "ai"


_TIER_LIMITS = {
    RateTier.public: lambda: settings.RATE_LIMIT_PUBLIC,
    RateTier.auth: lambda: settings.RATE_LIMIT_AUTH,
    RateTier.ai: lambda: settings.RATE_LIMIT_AI,
}

_WINDOW_SECONDS = 60


def _client_ip(request: Request) -> str:
    # Behind Cloudflare/Nginx the real IP is forwarded.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _enforce(scope: str, identity: str, limit: int) -> None:
    redis = get_redis()
    # Bucket the key by the current minute window.
    import time

    window = int(time.time()) // _WINDOW_SECONDS
    key = f"ratelimit:{scope}:{identity}:{window}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _WINDOW_SECONDS)
    if count > limit:
        raise RateLimitError(
            "Rate limit exceeded. Please slow down.",
            details={"limit": limit, "window_seconds": _WINDOW_SECONDS},
        )


def rate_limit(tier: RateTier) -> object:
    """Return a FastAPI dependency enforcing the given tier.

    Identity is the authenticated user id when available (sub claim), else the
    client IP. We read the bearer subject without full verification cost only
    for keying; actual auth still happens in route dependencies.
    """

    async def _dependency(request: Request) -> None:
        limit = _TIER_LIMITS[tier]()
        # Prefer a stable per-user identity for AI tier; fall back to IP.
        identity = _client_ip(request)
        if tier is RateTier.ai:
            auth = request.headers.get("Authorization", "")
            if auth:
                # Key by a short hash of the token to avoid storing it verbatim.
                import hashlib

                identity = hashlib.sha256(auth.encode()).hexdigest()[:32]
        await _enforce(tier.value, identity, limit)

    return _dependency
