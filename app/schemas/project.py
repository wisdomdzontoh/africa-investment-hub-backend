"""Project schemas (PRD §6.3). Public vs. gated detail is handled in the
service layer; these models expose optional fields that the service populates
only when the caller is entitled to them (NDA gate)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import FundingType, ProjectStage, ProjectStatus, RiskLevel
from app.schemas.common import ORMModel


class ProjectBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    sector: str = Field(min_length=1, max_length=64)
    country: str = Field(min_length=2, max_length=2)
    brief_description: str = Field(min_length=1, max_length=500)
    executive_summary: str | None = None
    full_description: str | None = None
    project_stage: ProjectStage
    funding_required: Decimal = Field(gt=0)
    funding_type: FundingType
    min_investment: Decimal | None = Field(default=None, ge=0)
    existing_funding: Decimal | None = Field(default=None, ge=0)
    use_of_funds: str | None = None
    expected_roi_min: Decimal | None = None
    expected_roi_max: Decimal | None = None
    timeline_to_returns_months: int | None = Field(default=None, ge=0)
    projected_revenue_12m: Decimal | None = None
    projected_revenue_24m: Decimal | None = None
    projected_revenue_36m: Decimal | None = None
    current_annual_revenue: Decimal | None = None


class ProjectCreate(ProjectBase):
    """Facilitator submission. ``full_description`` accepted but never shown publicly."""


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    brief_description: str | None = Field(default=None, max_length=500)
    executive_summary: str | None = None
    full_description: str | None = None
    project_stage: ProjectStage | None = None
    funding_required: Decimal | None = Field(default=None, gt=0)
    funding_type: FundingType | None = None
    min_investment: Decimal | None = None
    existing_funding: Decimal | None = None
    use_of_funds: str | None = None
    expected_roi_min: Decimal | None = None
    expected_roi_max: Decimal | None = None
    timeline_to_returns_months: int | None = None
    projected_revenue_12m: Decimal | None = None
    projected_revenue_24m: Decimal | None = None
    projected_revenue_36m: Decimal | None = None
    current_annual_revenue: Decimal | None = None


class ProjectCard(ORMModel):
    """Public listing card (PRD §6.1)."""

    id: uuid.UUID
    title: str
    sector: str
    country: str
    brief_description: str
    funding_required: Decimal
    funding_type: FundingType
    expected_roi_min: Decimal | None = None
    expected_roi_max: Decimal | None = None
    timeline_to_returns_months: int | None = None
    risk_level: RiskLevel | None = None
    project_stage: ProjectStage
    is_featured: bool = False
    created_at: datetime


class ProjectDetail(ProjectCard):
    """Detail view. ``executive_summary`` for approved investors;
    ``full_description`` only when NDA-signed (set by the service)."""

    executive_summary: str | None = None
    full_description: str | None = None
    min_investment: Decimal | None = None
    existing_funding: Decimal | None = None
    use_of_funds: str | None = None
    projected_revenue_12m: Decimal | None = None
    projected_revenue_24m: Decimal | None = None
    projected_revenue_36m: Decimal | None = None
    current_annual_revenue: Decimal | None = None
    view_count: int = 0


class ProjectOwnerOut(ProjectDetail):
    """Owner's view of their own submission, including status."""

    status: ProjectStatus
    documents: list[dict[str, Any]] = []
    updated_at: datetime


class ProjectAdminOut(ProjectOwnerOut):
    owner_user_id: uuid.UUID
    admin_notes: str | None = None
