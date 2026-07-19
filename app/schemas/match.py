"""Match and notification schemas (PRD §6.5, §10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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


class FacilitatorMatchInvestor(ORMModel):
    """The slice of an investor a facilitator may see (PRD §6.9): enough to
    recognise serious interest, never direct contact details — the platform
    team mediates all communication."""

    company_name: str | None = None
    country_of_registration: str | None = None


class FacilitatorMatchOut(ORMModel):
    """A match as shown to the project's facilitator. ``investor`` is ``None``
    while the engagement is confidential — identity withheld until the
    investor authorises introduction (PRD §6.9)."""

    id: uuid.UUID
    project_id: uuid.UUID
    project_title: str
    status: MatchStatus
    source: MatchSource
    is_confidential: bool = False
    investor_interest_at: datetime | None = None
    created_at: datetime
    investor: FacilitatorMatchInvestor | None = None


class AdminMatchOut(MatchOut):
    """Admin matches list — enriched with human-readable project/investor names."""

    project_title: str | None = None
    investor_company: str | None = None


class MatchCreate(BaseModel):
    """Admin manual match creation (PRD §6.4 Match Management)."""

    investor_id: uuid.UUID
    project_id: uuid.UUID
    explanation: str | None = None


class MatchStatusUpdate(BaseModel):
    status: MatchStatus


class ConfidentialUpdate(BaseModel):
    """Investor toggles confidential engagement before a facilitator intro."""

    confidential: bool


class DealRoomProject(ProjectCard):
    """Project view inside the deal room. ``full_description`` and
    ``documents`` are populated only when the NDA gate is unlocked."""

    executive_summary: str | None = None
    full_description: str | None = None
    documents: list[dict[str, Any]] = []


class DealRoomOut(BaseModel):
    """Per-match deal room (PRD §6.10). NDA gate decided server-side."""

    match: MatchOut
    project: DealRoomProject
    nda_unlocked: bool
    # True only while an NDA has been sent and is awaiting the investor's signature.
    can_sign_nda: bool


class DealDocumentUrl(BaseModel):
    url: str
    expires_in: int


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
