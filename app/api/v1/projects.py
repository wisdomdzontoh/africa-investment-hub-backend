"""Project endpoints (PRD §6.3, §11).

Public listing + detail (with the NDA gate applied in the service), plus
project-facilitator submission and management.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    DbDep,
    OptionalUser,
    PaginationDep,
    require_project_owner,
)
from app.core.config import settings
from app.core.rate_limit import RateTier, rate_limit
from app.models.enums import FundingType, ProjectStage, RiskLevel
from app.models.user import User
from app.schemas.common import (
    MessageResponse,
    Page,
    PresignUploadRequest,
    PresignUploadResponse,
)
from app.schemas.project import (
    ProjectCard,
    ProjectCreate,
    ProjectDetail,
    ProjectOwnerOut,
    ProjectUpdate,
)
from app.services import project_service, storage

router = APIRouter(prefix="/projects", tags=["projects"])

OwnerUser = Annotated[User, Depends(require_project_owner)]


@router.get("", response_model=Page[ProjectCard], dependencies=[Depends(rate_limit(RateTier.public))])
async def list_projects(
    db: DbDep,
    page: PaginationDep,
    sector: Annotated[list[str] | None, Query()] = None,
    country: Annotated[list[str] | None, Query()] = None,
    min_funding: Annotated[float | None, Query(ge=0)] = None,
    max_funding: Annotated[float | None, Query(ge=0)] = None,
    min_roi: Annotated[float | None, Query()] = None,
    max_roi: Annotated[float | None, Query()] = None,
    risk_level: Annotated[RiskLevel | None, Query()] = None,
    stage: Annotated[ProjectStage | None, Query()] = None,
    funding_type: Annotated[FundingType | None, Query()] = None,
    featured: Annotated[bool | None, Query()] = None,
    sort: Annotated[
        str | None,
        Query(
            description="newest|highest_roi|lowest_risk|most_viewed|funding_desc|funding_asc|featured"
        ),
    ] = None,
    page_number: Annotated[
        int | None,
        Query(alias="page", ge=1, description="1-based page for offset paging (adds `total`)"),
    ] = None,
) -> Page[ProjectCard]:
    filters = {
        "sector": sector,
        "country": country,
        "min_funding": min_funding,
        "max_funding": max_funding,
        "min_roi": min_roi,
        "max_roi": max_roi,
        "risk_level": risk_level,
        "stage": stage,
        "funding_type": funding_type,
        "featured": featured,
    }
    if page_number is not None:
        # Offset mode for the public site's numbered pager.
        items, total = await project_service.list_public_offset(
            db, filters=filters, sort=sort, page_number=page_number, page_size=page.limit
        )
        return Page[ProjectCard](
            items=[ProjectCard.model_validate(p) for p in items],
            has_more=page_number * page.limit < total,
            total=total,
        )

    rows = await project_service.list_public(db, filters=filters, sort=sort, page=page)
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    return Page[ProjectCard](
        items=[ProjectCard.model_validate(p) for p in items],
        next_cursor=str(items[-1].id) if has_more and items else None,
        has_more=has_more,
    )


# ── Owner routes (declared before /{id} so they are not shadowed) ──
@router.post("", response_model=ProjectOwnerOut, status_code=201)
async def submit_project(payload: ProjectCreate, db: DbDep, owner: OwnerUser) -> ProjectOwnerOut:
    project = await project_service.create(db, owner=owner, payload=payload)
    return ProjectOwnerOut.model_validate(project)


@router.get("/mine", response_model=Page[ProjectOwnerOut])
async def my_projects(db: DbDep, owner: OwnerUser, page: PaginationDep) -> Page[ProjectOwnerOut]:
    rows = await project_service.list_own(db, owner_id=owner.id, page=page)
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    return Page[ProjectOwnerOut](
        items=[ProjectOwnerOut.model_validate(p) for p in items],
        next_cursor=str(items[-1].id) if has_more and items else None,
        has_more=has_more,
    )


@router.get("/mine/{project_id}", response_model=ProjectOwnerOut)
async def my_project_detail(
    project_id: uuid.UUID, db: DbDep, owner: OwnerUser
) -> ProjectOwnerOut:
    """Owner's full view of their own project — any status, with documents."""
    project = await project_service.get_owned_or_404(db, project_id=project_id, owner_id=owner.id)
    return ProjectOwnerOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectDetail)
async def project_detail(project_id: uuid.UUID, db: DbDep, user: OptionalUser) -> ProjectDetail:
    project, visibility = await project_service.get_detail(db, project_id=project_id, user=user)
    await project_service.increment_view(db, project)
    detail = ProjectDetail.model_validate(project)
    # Apply gating decided by the service.
    if not visibility["executive_summary"]:
        detail.executive_summary = None
    if not visibility["full_description"]:
        detail.full_description = None
    return detail


@router.patch("/{project_id}", response_model=ProjectOwnerOut)
async def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, db: DbDep, owner: OwnerUser
) -> ProjectOwnerOut:
    project = await project_service.get_owned_or_404(db, project_id=project_id, owner_id=owner.id)
    updated = await project_service.update(db, project=project, payload=payload)
    return ProjectOwnerOut.model_validate(updated)


@router.post("/{project_id}/documents", response_model=PresignUploadResponse)
async def presign_project_document(
    project_id: uuid.UUID, payload: PresignUploadRequest, db: DbDep, owner: OwnerUser
) -> PresignUploadResponse:
    project = await project_service.get_owned_or_404(db, project_id=project_id, owner_id=owner.id)
    storage.validate_upload(payload.content_type)
    key = storage.build_key(prefix="project", owner_id=project.id, filename=payload.filename)
    url = storage.presign_put(key, payload.content_type)
    await project_service.add_document(
        db,
        project=project,
        doc={
            "type": payload.doc_type,
            "r2_key": key,
            "filename": payload.filename,
            "content_type": payload.content_type,
        },
    )
    return PresignUploadResponse(
        upload_url=url, r2_key=key, expires_in=settings.R2_PRESIGN_EXPIRY_SECONDS
    )


@router.delete("/{project_id}/documents/{r2_key:path}", response_model=MessageResponse)
async def delete_project_document(
    project_id: uuid.UUID, r2_key: str, db: DbDep, owner: OwnerUser
) -> MessageResponse:
    project = await project_service.get_owned_or_404(db, project_id=project_id, owner_id=owner.id)
    storage.delete_object(r2_key)
    await project_service.remove_document(db, project=project, r2_key=r2_key)
    return MessageResponse(message="Document deleted.")
