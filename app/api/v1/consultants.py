"""Consultant endpoints (PRD §6.11, §11)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ApprovedUser, CurrentUser, DbDep, PaginationDep, require_role
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.common import Page, PresignUploadRequest, PresignUploadResponse
from app.schemas.consultant import (
    ConsultantCard,
    ConsultantOut,
    ConsultantRegister,
    ConsultantUpdate,
)
from app.services import consultant_service, storage

router = APIRouter(prefix="/consultants", tags=["consultants"])

# Consultants register as users with the project_owner role acting as partners,
# or a dedicated consultant flow. We allow any authenticated user to create a
# consultant profile; discovery is restricted to approved investors.
ConsultantSelf = Annotated[User, Depends(require_role(UserRole.project_owner, UserRole.investor, UserRole.admin))]


@router.post("/register", response_model=ConsultantOut, status_code=201)
async def register(payload: ConsultantRegister, db: DbDep, user: CurrentUser) -> ConsultantOut:
    profile = await consultant_service.register(db, user=user, payload=payload)
    return ConsultantOut.model_validate(profile)


@router.get("/me", response_model=ConsultantOut)
async def get_me(db: DbDep, user: CurrentUser) -> ConsultantOut:
    profile = await consultant_service.get_by_user(db, user.id)
    if profile is None:
        raise NotFoundError("Consultant profile not found.")
    return ConsultantOut.model_validate(profile)


@router.patch("/me", response_model=ConsultantOut)
async def update_me(payload: ConsultantUpdate, db: DbDep, user: CurrentUser) -> ConsultantOut:
    profile = await consultant_service.get_by_user(db, user.id)
    if profile is None:
        raise NotFoundError("Consultant profile not found.")
    updated = await consultant_service.update(db, profile=profile, payload=payload)
    return ConsultantOut.model_validate(updated)


@router.get("", response_model=Page[ConsultantCard])
async def search(
    db: DbDep,
    _investor: ApprovedUser,
    page: PaginationDep,
    expertise: Annotated[str | None, Query()] = None,
    country: Annotated[str | None, Query()] = None,
    sector: Annotated[str | None, Query()] = None,
) -> Page[ConsultantCard]:
    """Investor-only search over approved consultants (PRD §6.11)."""
    rows = await consultant_service.search_approved(
        db, expertise=expertise, country=country, sector=sector, page=page
    )
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    return Page[ConsultantCard](
        items=[ConsultantCard.model_validate(c) for c in items],
        next_cursor=str(items[-1].id) if has_more and items else None,
        has_more=has_more,
    )


@router.get("/{consultant_id}", response_model=ConsultantOut)
async def get_consultant(
    consultant_id: uuid.UUID, db: DbDep, _investor: ApprovedUser
) -> ConsultantOut:
    profile = await consultant_service.get_approved_or_404(db, consultant_id)
    return ConsultantOut.model_validate(profile)


@router.post("/me/documents", response_model=PresignUploadResponse)
async def presign_document(
    payload: PresignUploadRequest, db: DbDep, user: CurrentUser
) -> PresignUploadResponse:
    profile = await consultant_service.get_by_user(db, user.id)
    if profile is None:
        raise NotFoundError("Consultant profile not found.")
    storage.validate_upload(payload.content_type)
    key = storage.build_key(prefix="consultant", owner_id=profile.id, filename=payload.filename)
    url = storage.presign_put(key, payload.content_type)
    await consultant_service.add_document(
        db,
        profile=profile,
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
