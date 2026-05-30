"""Admin CMS endpoints — country content + homepage (PRD §6.4, §13)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AdminUser, DbDep
from app.schemas.country import (
    CountryContentAdmin,
    CountryContentUpsert,
    CountrySummary,
    CountryVersionOut,
)
from app.schemas.homepage import HomepageContentOut, HomepageContentUpdate
from app.services import audit_service, cms_service

router = APIRouter(prefix="/cms", tags=["admin-cms"])


@router.get("/countries", response_model=list[CountrySummary])
async def list_countries(db: DbDep, _: AdminUser) -> list[CountrySummary]:
    rows = await cms_service.list_all_countries(db)
    return [CountrySummary.model_validate(c) for c in rows]


@router.get("/countries/{country_code}", response_model=CountryContentAdmin)
async def get_country(country_code: str, db: DbDep, _: AdminUser) -> CountryContentAdmin:
    country = await cms_service.get_country(db, country_code)
    return cms_service._to_admin_schema(country)


@router.put("/countries/{country_code}", response_model=CountryContentAdmin)
async def upsert_country(
    country_code: str, payload: CountryContentUpsert, db: DbDep, admin: AdminUser
) -> CountryContentAdmin:
    result = await cms_service.upsert_country(
        db, country_code=country_code, payload=payload, editor_id=admin.id
    )
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="cms.country_saved",
        target_type="country_content",
        metadata={"country_code": country_code.upper(), "published": payload.publish},
    )
    return result


@router.get("/countries/{country_code}/versions", response_model=list[CountryVersionOut])
async def list_versions(country_code: str, db: DbDep, _: AdminUser) -> list[CountryVersionOut]:
    rows = await cms_service.list_versions(db, country_code)
    return [CountryVersionOut.model_validate(v) for v in rows]


@router.get("/homepage", response_model=HomepageContentOut)
async def get_homepage(db: DbDep, _: AdminUser) -> HomepageContentOut:
    content = await cms_service.get_homepage(db)
    return HomepageContentOut.model_validate(content)


@router.put("/homepage", response_model=HomepageContentOut)
async def update_homepage(
    payload: HomepageContentUpdate, db: DbDep, admin: AdminUser
) -> HomepageContentOut:
    content = await cms_service.update_homepage(db, payload=payload, editor_id=admin.id)
    await audit_service.record(
        db, actor_user_id=admin.id, action="cms.homepage_saved", target_type="homepage_content"
    )
    return HomepageContentOut.model_validate(content)
