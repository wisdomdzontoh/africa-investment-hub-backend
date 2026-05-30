"""Admin-specific schemas (audit log, analytics)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class AuditLogOut(ORMModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    action: str
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    created_at: datetime

    # Map the DB attribute ``audit_metadata`` to the API field ``metadata``.
    metadata: dict[str, Any] = {}

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "AuditLogOut":  # type: ignore[override]
        if hasattr(obj, "audit_metadata"):
            data = {
                "id": obj.id,
                "actor_user_id": obj.actor_user_id,
                "action": obj.action,
                "target_type": obj.target_type,
                "target_id": obj.target_id,
                "created_at": obj.created_at,
                "metadata": obj.audit_metadata,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


class AnalyticsOverview(ORMModel):
    investors_by_status: dict[str, int] = {}
    projects_by_status: dict[str, int] = {}
    projects_by_sector: dict[str, int] = {}
    matches_by_status: dict[str, int] = {}
    total_users: int = 0
