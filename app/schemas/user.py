"""User schemas (PRD §6.4 User Management, §10)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import Locale, UserRole, UserStatus
from app.schemas.common import ORMModel


class UserOut(ORMModel):
    id: uuid.UUID
    clerk_id: str
    email: str | None = None
    role: UserRole
    status: UserStatus
    locale: Locale
    created_at: datetime
    # True once the user has submitted a role-specific profile (investor /
    # consultant) or at least one project. Drives onboarding-vs-portal routing.
    onboarding_complete: bool = False


class AccountRoleSet(BaseModel):
    """Onboarding role selection — investor or project owner only."""

    role: UserRole = Field(description="Platform role chosen during onboarding.")


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserStatusUpdate(BaseModel):
    status: UserStatus


class LocaleUpdate(BaseModel):
    locale: Locale
