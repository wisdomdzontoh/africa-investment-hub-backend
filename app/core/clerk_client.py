"""Clerk Backend API client (PRD §14).

Server-side half of the bidirectional Clerk↔DB identity sync:
metadata (roles) push, account deletion, ban/unban on suspension, and the
user listing used by the nightly reconciliation job. The browser never talks
to this API — every call here requires ``CLERK_SECRET_KEY``.

Mutating calls are *best-effort with a durable backstop*: the local DB row is
the source of intent (e.g. ``deleted_at``), and the reconciliation cron
re-drives any call that failed transiently, so a Clerk outage never blocks a
user-facing request or loses a deletion.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

_CLERK_API = "https://api.clerk.com/v1"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"}


async def delete_user(clerk_id: str) -> bool:
    """Delete the Clerk account for ``clerk_id``. Idempotent: a 404 (already
    gone) counts as success. Returns ``False`` on transient failure — the
    caller's DB state is authoritative and reconciliation retries later."""
    if not settings.CLERK_SECRET_KEY:
        logger.warning("CLERK_SECRET_KEY not configured — skipping Clerk user deletion.")
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.delete(
                f"{_CLERK_API}/users/{clerk_id}", headers=_auth_headers()
            )
    except httpx.HTTPError:
        logger.exception("Clerk user deletion failed for %s", clerk_id)
        return False

    if resp.status_code == 404 or resp.status_code < 400:
        return True
    logger.error(
        "Clerk user deletion failed: %s %s", resp.status_code, resp.text
    )
    return False


async def _set_banned(clerk_id: str, *, banned: bool) -> bool:
    """Ban or unban a Clerk user (defense-in-depth on admin suspension; the
    request-level ``_ensure_active_user`` check remains the enforcement point)."""
    if not settings.CLERK_SECRET_KEY:
        logger.warning("CLERK_SECRET_KEY not configured — skipping Clerk %s.",
                       "ban" if banned else "unban")
        return False

    action = "ban" if banned else "unban"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_CLERK_API}/users/{clerk_id}/{action}", headers=_auth_headers()
            )
    except httpx.HTTPError:
        logger.exception("Clerk %s failed for %s", action, clerk_id)
        return False

    if resp.status_code < 400:
        return True
    logger.error("Clerk %s failed: %s %s", action, resp.status_code, resp.text)
    return False


async def ban_user(clerk_id: str) -> bool:
    return await _set_banned(clerk_id, banned=True)


async def unban_user(clerk_id: str) -> bool:
    return await _set_banned(clerk_id, banned=False)


async def list_users(*, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Page through Clerk's user list (reconciliation). Returns ``[]`` when
    unconfigured or on failure — the cron logs and tries again next run."""
    if not settings.CLERK_SECRET_KEY:
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{_CLERK_API}/users",
                headers=_auth_headers(),
                params={"limit": limit, "offset": offset, "order_by": "+created_at"},
            )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        logger.exception("Clerk user listing failed (offset=%d)", offset)
        return []

    return data if isinstance(data, list) else data.get("data", [])


async def update_user_public_metadata(clerk_id: str, public_metadata: dict[str, Any]) -> None:
    """Merge ``public_metadata`` onto the Clerk user (requires CLERK_SECRET_KEY)."""
    if not settings.CLERK_SECRET_KEY:
        logger.warning("CLERK_SECRET_KEY not configured — skipping Clerk metadata sync.")
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.patch(
            f"{_CLERK_API}/users/{clerk_id}/metadata",
            headers={"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"},
            json={"public_metadata": public_metadata},
        )

    if resp.status_code >= 400:
        logger.error("Clerk metadata update failed: %s %s", resp.status_code, resp.text)
        raise AppError(
            "Failed to sync account role with authentication provider.",
            code="clerk_sync_failed",
            status_code=502,
        )


async def create_invitation(
    *, email: str, role: str, redirect_url: str | None = None
) -> None:
    """Send a Clerk invitation that bakes ``role`` into the new user's
    public_metadata. On sign-up the Clerk webhook creates the local user with
    that role — so an invited admin is provisioned without any password
    handling on our side, and the role can't be spoofed by the recipient."""
    if not settings.CLERK_SECRET_KEY:
        raise AppError(
            "Invitations require the authentication provider to be configured.",
            code="clerk_not_configured",
            status_code=503,
        )

    payload: dict[str, Any] = {
        "email_address": email,
        "public_metadata": {"role": role},
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_CLERK_API}/invitations",
            headers={"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"},
            json=payload,
        )

    if resp.status_code >= 400:
        logger.error("Clerk invitation failed: %s %s", resp.status_code, resp.text)
        # 422 from Clerk most commonly means the email already has an account.
        if resp.status_code == 422:
            raise AppError(
                "That email already has an account or a pending invitation.",
                code="invite_conflict",
                status_code=409,
            )
        raise AppError(
            "Failed to send the invitation.",
            code="clerk_invite_failed",
            status_code=502,
        )
