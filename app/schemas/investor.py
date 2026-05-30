"""Investor profile schemas (PRD §6.2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import RiskLevel, UserStatus
from app.schemas.common import ORMModel


class PreviousProject(BaseModel):
    project_name: str
    country: str | None = None
    sector: str | None = None
    year: int | None = None
    description: str | None = None


class InvestorBase(BaseModel):
    # Section A — Company
    company_name: str = Field(min_length=1, max_length=255)
    country_of_registration: str = Field(min_length=2, max_length=2)
    registration_number: str | None = None
    years_of_operation: int | None = Field(default=None, ge=0)
    registered_address: str | None = None
    website: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None

    # Section B — Investment profile
    investment_countries: list[str] = []
    investment_sectors: list[str] = []
    investment_types: list[str] = []
    min_ticket_size: Decimal | None = Field(default=None, ge=0)
    max_ticket_size: Decimal | None = Field(default=None, ge=0)
    preferred_deal_size: Decimal | None = Field(default=None, ge=0)
    capital_availability: Decimal | None = Field(default=None, ge=0)

    # Section C — Risk and returns
    risk_appetite: RiskLevel | None = None
    target_roi_min: Decimal | None = None
    target_roi_max: Decimal | None = None
    time_horizon: str | None = None
    preferred_ownership_structures: list[str] = []
    exit_strategy: str | None = None
    preferred_ownership_pct_min: Decimal | None = Field(default=None, ge=0, le=100)
    preferred_ownership_pct_max: Decimal | None = Field(default=None, ge=0, le=100)

    # Section D — Compliance and ESG
    esg_requirements: str | None = None
    sectors_excluded: list[str] = []
    political_risk_tolerance: str | None = None
    currency_risk_tolerance: str | None = None

    # Section E — Track record
    previous_projects: list[PreviousProject] = Field(default_factory=list, max_length=5)
    certifications: str | None = None


class InvestorRegister(InvestorBase):
    """Full intake submission (multi-step form, sent on final submit)."""


class InvestorUpdate(BaseModel):
    """Partial update — any subset of editable preference fields (PRD §6.5)."""

    company_name: str | None = None
    registered_address: str | None = None
    website: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    investment_countries: list[str] | None = None
    investment_sectors: list[str] | None = None
    investment_types: list[str] | None = None
    min_ticket_size: Decimal | None = None
    max_ticket_size: Decimal | None = None
    preferred_deal_size: Decimal | None = None
    capital_availability: Decimal | None = None
    risk_appetite: RiskLevel | None = None
    target_roi_min: Decimal | None = None
    target_roi_max: Decimal | None = None
    time_horizon: str | None = None
    preferred_ownership_structures: list[str] | None = None
    exit_strategy: str | None = None
    esg_requirements: str | None = None
    sectors_excluded: list[str] | None = None
    political_risk_tolerance: str | None = None
    currency_risk_tolerance: str | None = None


class DocumentMeta(BaseModel):
    type: str
    r2_key: str
    filename: str
    uploaded_at: datetime | None = None
    content_type: str | None = None
    size: int | None = None


class InvestorOut(ORMModel, InvestorBase):
    id: uuid.UUID
    user_id: uuid.UUID
    documents: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime


class InvestorAdminOut(InvestorOut):
    """Admin view includes account status (sourced from the linked User and
    set by the route, so it carries a default for ORM validation)."""

    status: UserStatus = UserStatus.pending
