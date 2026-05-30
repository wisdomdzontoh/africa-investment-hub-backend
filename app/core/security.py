"""Clerk authentication — JWKS-based JWT verification (PRD §8.5, §14).

Clerk signs session JWTs with rotating RSA keys published at a JWKS endpoint.
We fetch and cache the JWKS in Redis (10-minute TTL) to avoid a network call
on every request, then verify each incoming token's signature, expiry, and
issuer. The user's role lives in ``publicMetadata.role`` and is set server-side
only — never trusted from the client.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.enums import UserRole

logger = get_logger(__name__)

_JWKS_CACHE_KEY = "auth:clerk:jwks"

# Tolerate minor clock drift between this host and Clerk when checking the
# token's exp/nbf/iat. Mirrors what Clerk's own backend SDKs do; without it,
# a host clock running a few seconds behind rejects freshly minted tokens
# (ImmatureSignatureError on `iat`).
_CLOCK_SKEW_LEEWAY = timedelta(seconds=60)


@dataclass(slots=True)
class ClerkClaims:
    """Verified claims extracted from a Clerk session token."""

    clerk_id: str
    email: str | None
    role: UserRole | None
    raw: dict[str, Any]


async def _fetch_jwks() -> dict[str, Any]:
    """Return the Clerk JWKS, served from Redis cache when warm."""
    redis = get_redis()
    cached = await redis.get(_JWKS_CACHE_KEY)
    if cached:
        return json.loads(cached)

    if not settings.CLERK_JWKS_URL:
        raise UnauthorizedError("Auth is not configured (missing CLERK_JWKS_URL).")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.CLERK_JWKS_URL)
        resp.raise_for_status()
        jwks = resp.json()

    await redis.set(_JWKS_CACHE_KEY, json.dumps(jwks), ex=settings.JWKS_CACHE_TTL_SECONDS)
    return jwks


def _signing_key(jwks: dict[str, Any], kid: str) -> PyJWK:
    key_set = PyJWKSet.from_dict(jwks)
    for key in key_set.keys:
        if key.key_id == kid:
            return key
    raise UnauthorizedError("Signing key not found for token.")


def _extract_role(claims: dict[str, Any]) -> UserRole | None:
    # Clerk can surface publicMetadata at the top level (via a JWT template) or
    # nested. Support both shapes.
    meta = claims.get("public_metadata") or claims.get("publicMetadata") or {}
    role = claims.get("role") or (meta.get("role") if isinstance(meta, dict) else None)
    if not role:
        return None
    try:
        return UserRole(role)
    except ValueError:
        logger.warning("Unknown role in token: %s", role)
        return None


async def verify_token(token: str) -> ClerkClaims:
    """Verify a Clerk JWT and return its claims, or raise ``UnauthorizedError``."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Malformed authentication token.") from exc

    kid = header.get("kid")
    if not kid:
        raise UnauthorizedError("Token missing key id.")

    jwks = await _fetch_jwks()
    signing_key = _signing_key(jwks, kid)

    options = {"verify_aud": bool(settings.CLERK_AUDIENCE)}
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.CLERK_AUDIENCE or None,
            issuer=settings.CLERK_ISSUER or None,
            leeway=_CLOCK_SKEW_LEEWAY,
            options=options,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Authentication token has expired.") from exc
    except jwt.PyJWTError as exc:
        # Log the precise reason + the token's own iss/aud so misconfigured JWT
        # templates are diagnosable without leaking the signature.
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            token_iss = unverified.get("iss")
            token_aud = unverified.get("aud")
        except Exception:  # pragma: no cover - best-effort diagnostics
            token_iss = token_aud = "<unparseable>"
        logger.warning(
            "JWT verification failed (%s): %s | token iss=%r aud=%r | "
            "expected iss=%r aud=%r",
            type(exc).__name__,
            exc,
            token_iss,
            token_aud,
            settings.CLERK_ISSUER or None,
            settings.CLERK_AUDIENCE or None,
        )
        raise UnauthorizedError("Invalid authentication token.") from exc

    clerk_id = claims.get("sub")
    if not clerk_id:
        raise UnauthorizedError("Token missing subject.")

    return ClerkClaims(
        clerk_id=clerk_id,
        email=claims.get("email"),
        role=_extract_role(claims),
        raw=claims,
    )
