"""Public country endpoints (PRD §6.1, §11)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import DbDep, LocaleDep
from app.core.rate_limit import RateTier, rate_limit
from app.schemas.country import CountryDetailPublic, CountrySummary
from app.services import country_service

router = APIRouter(
    prefix="/countries",
    tags=["countries"],
    dependencies=[Depends(rate_limit(RateTier.public))],
)


@router.get("", response_model=list[CountrySummary])
async def list_countries(db: DbDep) -> list[CountrySummary]:
    return await country_service.list_published(db)


@router.get("/{country_code}", response_model=CountryDetailPublic)
async def country_detail(
    country_code: str, db: DbDep, locale: LocaleDep
) -> CountryDetailPublic:
    return await country_service.get_published_detail(
        db, country_code=country_code, locale=locale
    )
