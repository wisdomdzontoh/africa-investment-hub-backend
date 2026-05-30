"""Country regulatory content — public read path (PRD §6.1, §7)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.i18n import localize
from app.models.country import CountryContent
from app.models.enums import Locale
from app.schemas.country import CountryDetailPublic, CountrySummary

# Localised rich-text sections to resolve per request.
_LOCALISED_SECTIONS = (
    "investment_climate",
    "investment_laws",
    "tax_system",
    "business_registration",
    "licensing_requirements",
    "foreign_ownership_rules",
    "repatriation_policy",
    "immigration_requirements",
)


async def list_published(db: AsyncSession) -> list[CountrySummary]:
    result = await db.execute(
        select(CountryContent).order_by(CountryContent.country_name.asc())
    )
    return [CountrySummary.model_validate(c) for c in result.scalars().all()]


async def get_published_detail(
    db: AsyncSession, *, country_code: str, locale: Locale
) -> CountryDetailPublic:
    """Return a published country page with each section resolved to ``locale``
    (falling back to English when a translation is missing)."""
    result = await db.execute(
        select(CountryContent).where(CountryContent.country_code == country_code.upper())
    )
    country = result.scalar_one_or_none()
    if country is None or not country.is_published:
        raise NotFoundError("Country content not found.")

    localised = {
        section: localize(getattr(country, section), locale) for section in _LOCALISED_SECTIONS
    }
    return CountryDetailPublic(
        country_code=country.country_code,
        country_name=country.country_name,
        region=country.region,
        key_contacts=country.key_contacts,
        recent_news=country.recent_news,
        last_updated_at=country.last_updated_at,
        **localised,
    )
