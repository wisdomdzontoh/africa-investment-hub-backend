"""Consultant/partner schemas (PRD §6.11)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ConsultantStatus, ContactPreference
from app.schemas.common import ORMModel


class ConsultantBase(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    title: str | None = None
    country: str = Field(min_length=2, max_length=2)
    city: str | None = None
    expertise_areas: list[str] = []
    sectors_served: list[str] = []
    years_of_experience: int | None = Field(default=None, ge=0)
    languages_spoken: list[str] = []
    bio: str | None = None
    key_achievements: str | None = None
    contact_preference: ContactPreference = ContactPreference.platform_message


class ConsultantRegister(ConsultantBase):
    pass


class ConsultantUpdate(BaseModel):
    full_name: str | None = None
    title: str | None = None
    country: str | None = None
    city: str | None = None
    expertise_areas: list[str] | None = None
    sectors_served: list[str] | None = None
    years_of_experience: int | None = None
    languages_spoken: list[str] | None = None
    bio: str | None = None
    key_achievements: str | None = None
    contact_preference: ContactPreference | None = None


class ConsultantCard(ORMModel):
    """Card shown to approved investors in search results."""

    id: uuid.UUID
    full_name: str
    title: str | None = None
    country: str
    city: str | None = None
    expertise_areas: list[str] = []
    sectors_served: list[str] = []
    years_of_experience: int | None = None
    languages_spoken: list[str] = []
    is_verified: bool = False


class ConsultantOut(ConsultantCard):
    bio: str | None = None
    key_achievements: str | None = None
    contact_preference: ContactPreference
    documents: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime


class ConsultantAdminOut(ConsultantOut):
    user_id: uuid.UUID
    status: ConsultantStatus
