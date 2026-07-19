"""Due-diligence endpoints (PRD §6.8, P2-05).

A DD request hangs off a match. The matched investor or the facilitator can
request it (post-NDA) and upload evidence per checklist item; an admin signs
items off. Access mirrors the deal room (investor / facilitator / admin).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import AdminUser, CurrentUser, DbDep
from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.enums import NDA_UNLOCKED_STATUSES, UserRole
from app.schemas.common import (
    DocumentUrlResponse,
    PresignUploadRequest,
    PresignUploadResponse,
)
from app.schemas.due_diligence import DDItemStatusUpdate, DueDiligenceOut
from app.services import due_diligence_service as dd_service
from app.services import match_service, storage

router = APIRouter(tags=["due-diligence"])


@router.post(
    "/matches/{match_id}/due-diligence", response_model=DueDiligenceOut, status_code=201
)
async def request_due_diligence(
    match_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> DueDiligenceOut:
    match = await match_service.get_accessible_match(db, match_id=match_id, user=user)
    # Investors can only open DD once the NDA is signed; admins anytime.
    if user.role != UserRole.admin and match.status not in NDA_UNLOCKED_STATUSES:
        raise ForbiddenError("Sign the NDA before requesting due diligence.")
    dd = await dd_service.create_for_match(db, match=match)
    return DueDiligenceOut.model_validate(dd)


@router.get("/matches/{match_id}/due-diligence", response_model=DueDiligenceOut)
async def get_due_diligence(
    match_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> DueDiligenceOut:
    match = await match_service.get_accessible_match(db, match_id=match_id, user=user)
    dd = await dd_service.get_for_match(db, match.id)
    if dd is None:
        raise NotFoundError("Due diligence hasn't been requested for this match.")
    return DueDiligenceOut.model_validate(dd)


async def _accessible_dd(db: DbDep, dd_id: uuid.UUID, user):
    dd = await dd_service.get_or_404(db, dd_id)
    # Authorise via the parent match (raises 403/404 as appropriate).
    await match_service.get_accessible_match(db, match_id=dd.match_id, user=user)
    return dd


@router.post(
    "/due-diligence/{dd_id}/items/{item_id}/document",
    response_model=PresignUploadResponse,
)
async def upload_item_document(
    dd_id: uuid.UUID,
    item_id: str,
    payload: PresignUploadRequest,
    db: DbDep,
    user: CurrentUser,
) -> PresignUploadResponse:
    dd = await _accessible_dd(db, dd_id, user)
    storage.validate_upload(payload.content_type)
    key = storage.build_key(prefix="due-diligence", owner_id=dd.id, filename=payload.filename)
    url = storage.presign_put(key, payload.content_type)
    await dd_service.set_item_document(
        db, dd=dd, item_id=item_id, r2_key=key, filename=payload.filename
    )
    return PresignUploadResponse(
        upload_url=url, r2_key=key, expires_in=settings.R2_PRESIGN_EXPIRY_SECONDS
    )


@router.get(
    "/due-diligence/{dd_id}/items/{item_id}/document", response_model=DocumentUrlResponse
)
async def download_item_document(
    dd_id: uuid.UUID, item_id: str, db: DbDep, user: CurrentUser
) -> DocumentUrlResponse:
    dd = await _accessible_dd(db, dd_id, user)
    item = next((i for i in dd.checklist if i.get("item_id") == item_id), None)
    if item is None or not item.get("document_r2_key"):
        raise NotFoundError("No document uploaded for this item.")
    url = storage.presign_get(item["document_r2_key"], accessor_id=user.id)
    return DocumentUrlResponse(url=url, expires_in=settings.R2_PRESIGN_EXPIRY_SECONDS)


@router.patch("/due-diligence/{dd_id}/items/{item_id}", response_model=DueDiligenceOut)
async def update_item_status(
    dd_id: uuid.UUID,
    item_id: str,
    payload: DDItemStatusUpdate,
    db: DbDep,
    _admin: AdminUser,
) -> DueDiligenceOut:
    """Admin signs off (or rejects) a checklist item."""
    dd = await dd_service.get_or_404(db, dd_id)
    updated = await dd_service.set_item_status(
        db, dd=dd, item_id=item_id, status=payload.status
    )
    return DueDiligenceOut.model_validate(updated)
