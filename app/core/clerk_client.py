"""Clerk Backend API — sync publicMetadata (roles) server-side (PRD §14)."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

_CLERK_API = "https://api.clerk.com/v1"


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
