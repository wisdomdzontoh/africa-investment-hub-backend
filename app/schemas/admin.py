"""Admin-specific schemas (audit log, analytics)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

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


class RiskAssessmentOut(BaseModel):
    """AI risk assessment result (advisory). The admin sets the final
    risk_level on approval; this never auto-applies."""

    assessment: dict[str, Any] = {}
    admin_notes: str | None = None


class AnalyticsOverview(ORMModel):
    investors_by_status: dict[str, int] = {}
    users_by_role: dict[str, int] = {}
    projects_by_status: dict[str, int] = {}
    projects_by_sector: dict[str, int] = {}
    matches_by_status: dict[str, int] = {}
    total_users: int = 0
    total_matches: int = 0
    # Mean AI compatibility score across all matches (0–1); a coarse signal of
    # match quality for the admin dashboard (PRD §6.4, P2-09).
    avg_match_score: float | None = None
