"""Country regulatory content schemas (PRD §6.4).

Public responses are *localised* (a single string per section, resolved from
the JSONB ``{en, fr, zh}`` value). Admin/CMS responses carry the full locale
dict so the editor can show all tabs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel

LocaleText = dict[str, str]  # {"en": "...", "fr": "...", "zh": "..."}


class CountrySummary(ORMModel):
    country_code: str
    country_name: str
    region: str | None = None
    is_published: bool


class CountryDetailPublic(BaseModel):
    """Localised, published country page (PRD §6.1 Countries page)."""

    country_code: str
    country_name: str
    region: str | None = None
    investment_climate: str | None = None
    investment_laws: str | None = None
    tax_system: str | None = None
    business_registration: str | None = None
    licensing_requirements: str | None = None
    foreign_ownership_rules: str | None = None
    repatriation_policy: str | None = None
    immigration_requirements: str | None = None
    key_contacts: list[dict[str, Any]] = []
    recent_news: list[dict[str, Any]] = []
    last_updated_at: datetime | None = None


class CountryContentAdmin(BaseModel):
    """Full multi-locale content for the CMS editor."""

    country_code: str
    country_name: str
    region: str | None = None
    investment_climate: LocaleText | None = None
    investment_laws: LocaleText | None = None
    tax_system: LocaleText | None = None
    business_registration: LocaleText | None = None
    licensing_requirements: LocaleText | None = None
    foreign_ownership_rules: LocaleText | None = None
    repatriation_policy: LocaleText | None = None
    immigration_requirements: LocaleText | None = None
    key_contacts: list[dict[str, Any]] = []
    recent_news: list[dict[str, Any]] = []
    is_published: bool = False


class CountryContentUpsert(BaseModel):
    """Save draft or publish. ``publish`` toggles ``is_published``."""

    country_name: str | None = None
    region: str | None = None
    investment_climate: LocaleText | None = None
    investment_laws: LocaleText | None = None
    tax_system: LocaleText | None = None
    business_registration: LocaleText | None = None
    licensing_requirements: LocaleText | None = None
    foreign_ownership_rules: LocaleText | None = None
    repatriation_policy: LocaleText | None = None
    immigration_requirements: LocaleText | None = None
    key_contacts: list[dict[str, Any]] | None = None
    recent_news: list[dict[str, Any]] | None = None
    publish: bool = False


class CountryVersionOut(ORMModel):
    id: Any
    country_code: str
    created_at: datetime
    edited_by: Any | None = None
