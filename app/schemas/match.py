"""Match and notification schemas (PRD §6.5, §10)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import MatchSource, MatchStatus
from app.schemas.common import ORMModel
from app.schemas.project import ProjectCard


class MatchOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    score: float | None = None
    explanation: str | None = None
    source: MatchSource
    status: MatchStatus
    is_confidential: bool = False
    created_at: datetime


class MatchWithProject(MatchOut):
    project: ProjectCard


class MatchCreate(BaseModel):
    """Admin manual match creation (PRD §6.4 Match Management)."""

    investor_id: uuid.UUID
    project_id: uuid.UUID
    explanation: str | None = None


class MatchStatusUpdate(BaseModel):
    status: MatchStatus


class NotificationOut(ORMModel):
    id: uuid.UUID
    type: str
    title: str
    body: str | None = None
    link: str | None = None
    is_read: bool
    created_at: datetime


class NotificationReadUpdate(BaseModel):
    is_read: bool = True


class AdminStatusUpdate(BaseModel):
    """Generic admin status transition with optional reason (PRD §6.4)."""

    action: str = Field(description="approve | reject | suspend | request_info | verify | feature")
    reason: str | None = None
    risk_level: str | None = Field(default=None, description="Required when approving a project")
