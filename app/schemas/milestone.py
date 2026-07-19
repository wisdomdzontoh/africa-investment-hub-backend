"""Project milestone schemas — monitoring dashboard (PRD §6.6)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import MilestoneStatus
from app.schemas.common import ORMModel


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: MilestoneStatus = MilestoneStatus.pending


class MilestoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_date: date | None = None
    status: MilestoneStatus | None = None


class MilestoneOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None = None
    due_date: date | None = None
    status: MilestoneStatus
    created_at: datetime
    updated_at: datetime
