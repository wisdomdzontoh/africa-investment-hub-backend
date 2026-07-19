"""Due-diligence schemas (PRD §6.8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.models.enums import DueDiligenceStatus
from app.schemas.common import ORMModel

# Per-item lifecycle (checklist items live in the request's JSONB ``checklist``).
DDItemStatus = Literal["pending", "submitted", "approved", "rejected"]


class DueDiligenceOut(ORMModel):
    id: uuid.UUID
    match_id: uuid.UUID
    status: DueDiligenceStatus
    checklist: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime


class DDItemStatusUpdate(BaseModel):
    status: DDItemStatus
