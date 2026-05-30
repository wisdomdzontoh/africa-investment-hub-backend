"""Clerk webhooks — keep the local ``users`` table in sync (PRD §8.5).

Clerk signs webhooks with Svix. We verify the signature against
``CLERK_WEBHOOK_SECRET`` before processing ``user.created`` / ``user.updated``
/ ``user.deleted`` events.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import DbDep
from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.services import user_service

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(headers: dict[str, str], payload: bytes) -> dict[str, Any]:
    if not settings.CLERK_WEBHOOK_SECRET:
        raise UnauthorizedError("Webhook secret not configured.")
    from svix.webhooks import Webhook, WebhookVerificationError

    try:
        wh = Webhook(settings.CLERK_WEBHOOK_SECRET)
        return wh.verify(payload, headers)  # type: ignore[no-any-return]
    except WebhookVerificationError as exc:
        raise UnauthorizedError("Invalid webhook signature.") from exc


def _primary_email(data: dict[str, Any]) -> str | None:
    emails = data.get("email_addresses") or []
    primary_id = data.get("primary_email_address_id")
    for e in emails:
        if e.get("id") == primary_id:
            return e.get("email_address")
    return emails[0].get("email_address") if emails else None


def _role(data: dict[str, Any]) -> UserRole | None:
    meta = data.get("public_metadata") or {}
    role = meta.get("role")
    if not role:
        return None
    try:
        return UserRole(role)
    except ValueError:
        return None


@router.post("/clerk", status_code=200)
async def clerk_webhook(request: Request, db: DbDep) -> dict[str, str]:
    body = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    event = _verify_signature(headers, body)
    event_type = event.get("type")
    data = event.get("data", {})
    clerk_id = data.get("id")

    if not clerk_id:
        return {"status": "ignored"}

    if event_type in {"user.created", "user.updated"}:
        await user_service.upsert_from_webhook(
            db, clerk_id=clerk_id, email=_primary_email(data), role=_role(data)
        )
    elif event_type == "user.deleted":
        await user_service.soft_delete_by_clerk_id(db, clerk_id)
    else:
        logger.info("Unhandled Clerk webhook event: %s", event_type)

    return {"status": "ok"}
