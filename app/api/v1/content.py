"""Public site content (PRD §6.1) — CMS-backed homepage figures and
aggregate project counts. Read-heavy and identical for every visitor, so
responses are cached in Redis for a short TTL.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import DbDep
from app.core.rate_limit import RateTier, rate_limit
from app.core.redis import get_redis
from app.models.enums import ProjectStatus
from app.models.project import Project
from app.schemas.homepage import HomepageContentOut
from app.services import cms_service

router = APIRouter(
    prefix="/content",
    tags=["content"],
    dependencies=[Depends(rate_limit(RateTier.public))],
)

HOMEPAGE_CACHE_KEY = "cache:content:homepage"
_HOMEPAGE_TTL = 300
PROJECT_COUNTS_CACHE_KEY = "cache:content:project-counts"
_COUNTS_TTL = 60


@router.get("/homepage", response_model=HomepageContentOut)
async def homepage_content(db: DbDep) -> HomepageContentOut:
    """CMS-managed homepage content (stats, partner logos, team, advisory)."""
    redis = get_redis()
    cached = await redis.get(HOMEPAGE_CACHE_KEY)
    if cached:
        return HomepageContentOut.model_validate(json.loads(cached))

    content = HomepageContentOut.model_validate(await cms_service.get_homepage(db))
    await redis.set(HOMEPAGE_CACHE_KEY, content.model_dump_json(), ex=_HOMEPAGE_TTL)
    return content


@router.get("/project-counts")
async def project_counts(db: DbDep) -> dict[str, dict[str, int]]:
    """Approved-project counts per country code (Countries page badges)."""
    redis = get_redis()
    cached = await redis.get(PROJECT_COUNTS_CACHE_KEY)
    if cached:
        return {"counts": json.loads(cached)}

    result = await db.execute(
        select(Project.country, func.count())
        .where(Project.status == ProjectStatus.approved)
        .group_by(Project.country)
    )
    counts = {country: count for country, count in result.all()}
    await redis.set(PROJECT_COUNTS_CACHE_KEY, json.dumps(counts), ex=_COUNTS_TTL)
    return {"counts": counts}
