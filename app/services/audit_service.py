"""Audit logging service (PRD §14).

Every privileged/admin action is recorded. Helpers here are intentionally
side-effect-only: callers pass the acting user, action verb, and target.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit-log entry. Flushed (not committed) within the caller's tx."""
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        audit_metadata=metadata or {},
    )
    db.add(entry)
    await db.flush()
    return entry
