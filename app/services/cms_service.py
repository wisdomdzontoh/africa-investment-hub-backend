"""CMS service — country content + homepage editing (PRD §6.4, §13).

Country edits create a version snapshot (last 5 retained) and stamp the editor.
All translatable sections are JSONB ``{en, fr, zh}`` dicts; Phase 1 populates
only ``en``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.country import CountryContent, CountryContentVersion
from app.models.homepage import HomepageContent
from app.schemas.country import CountryContentAdmin, CountryContentUpsert
from app.schemas.homepage import HomepageContentUpdate

_VERSIONS_RETAINED = 5
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


async def list_all_countries(db: AsyncSession) -> list[CountryContent]:
    result = await db.execute(select(CountryContent).order_by(CountryContent.country_name))
    return list(result.scalars().all())


async def get_country(db: AsyncSession, country_code: str) -> CountryContent:
    result = await db.execute(
        select(CountryContent).where(CountryContent.country_code == country_code.upper())
    )
    country = result.scalar_one_or_none()
    if country is None:
        raise NotFoundError("Country content not found.")
    return country


def _to_admin_schema(country: CountryContent) -> CountryContentAdmin:
    return CountryContentAdmin.model_validate(
        {
            "country_code": country.country_code,
            "country_name": country.country_name,
            "region": country.region,
            **{s: getattr(country, s) for s in _LOCALISED_SECTIONS},
            "key_contacts": country.key_contacts,
            "recent_news": country.recent_news,
            "is_published": country.is_published,
        }
    )


def _snapshot(country: CountryContent) -> dict:
    return {
        "country_name": country.country_name,
        "region": country.region,
        **{s: getattr(country, s) for s in _LOCALISED_SECTIONS},
        "key_contacts": country.key_contacts,
        "recent_news": country.recent_news,
        "is_published": country.is_published,
    }


async def _prune_versions(db: AsyncSession, country_code: str) -> None:
    """Keep only the most recent ``_VERSIONS_RETAINED`` snapshots."""
    result = await db.execute(
        select(CountryContentVersion.id)
        .where(CountryContentVersion.country_code == country_code)
        .order_by(CountryContentVersion.created_at.desc())
        .offset(_VERSIONS_RETAINED)
    )
    stale = [row for row in result.scalars().all()]
    if stale:
        await db.execute(
            delete(CountryContentVersion).where(CountryContentVersion.id.in_(stale))
        )


async def upsert_country(
    db: AsyncSession,
    *,
    country_code: str,
    payload: CountryContentUpsert,
    editor_id: uuid.UUID,
) -> CountryContentAdmin:
    """Save draft or publish a country page, snapshotting the prior state."""
    code = country_code.upper()
    result = await db.execute(
        select(CountryContent).where(CountryContent.country_code == code)
    )
    country = result.scalar_one_or_none()

    if country is not None:
        # Snapshot existing state before mutating.
        db.add(
            CountryContentVersion(
                country_code=code, snapshot=_snapshot(country), edited_by=editor_id
            )
        )

    changed = payload.model_dump(exclude_unset=True, exclude={"publish"})
    if country is None:
        country = CountryContent(
            country_code=code,
            country_name=changed.pop("country_name", code),
            **changed,
        )
        db.add(country)
    else:
        for field, value in changed.items():
            setattr(country, field, value)

    country.is_published = payload.publish or country.is_published
    country.last_updated_by = editor_id
    await db.flush()
    await _prune_versions(db, code)
    await db.flush()

    # Refresh knowledge base for the chatbot when content is published.
    if payload.publish:
        from app.workers.queue import enqueue

        await enqueue("reindex_country", code)

    return _to_admin_schema(country)


async def list_versions(db: AsyncSession, country_code: str) -> list[CountryContentVersion]:
    result = await db.execute(
        select(CountryContentVersion)
        .where(CountryContentVersion.country_code == country_code.upper())
        .order_by(CountryContentVersion.created_at.desc())
        .limit(_VERSIONS_RETAINED)
    )
    return list(result.scalars().all())


# ─────────────────────────── Homepage ───────────────────────────
async def get_homepage(db: AsyncSession) -> HomepageContent:
    result = await db.execute(select(HomepageContent).limit(1))
    content = result.scalar_one_or_none()
    if content is None:
        content = HomepageContent()
        db.add(content)
        await db.flush()
    return content


async def update_homepage(
    db: AsyncSession, *, payload: HomepageContentUpdate, editor_id: uuid.UUID
) -> HomepageContent:
    content = await get_homepage(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(content, field, value)
    content.updated_by = editor_id
    await db.flush()
    return content
