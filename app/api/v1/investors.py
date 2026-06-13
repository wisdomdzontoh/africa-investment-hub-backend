"""Investor endpoints (PRD §6.2, §6.5, §11)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    CurrentUser,
    DbDep,
    PaginationDep,
    require_investor,
)
from app.core.exceptions import NotFoundError
from app.core.rate_limit import RateTier, rate_limit
from app.models.investor import InvestorProfile
from app.models.user import User
from app.schemas.common import (
    MessageResponse,
    Page,
    PresignUploadRequest,
    PresignUploadResponse,
)
from app.schemas.investor import InvestorOut, InvestorRegister, InvestorUpdate
from app.schemas.match import MatchWithProject, NotificationOut, NotificationReadUpdate
from app.services import investor_service, notification_service, storage

router = APIRouter(prefix="/investors", tags=["investors"])

InvestorUser = Annotated[User, Depends(require_investor)]


async def _own_profile(db: DbDep, user: User) -> InvestorProfile:
    profile = await investor_service.get_by_user(db, user.id)
    if profile is None:
        raise NotFoundError("Investor profile not found. Complete registration first.")
    return profile


@router.post(
    "/register",
    response_model=InvestorOut,
    status_code=201,
    dependencies=[Depends(rate_limit(RateTier.auth))],
)
async def register(payload: InvestorRegister, db: DbDep, user: InvestorUser) -> InvestorOut:
    profile = await investor_service.register(db, user=user, payload=payload)
    return InvestorOut.model_validate(profile)


@router.get("/me", response_model=InvestorOut)
async def get_me(db: DbDep, user: InvestorUser) -> InvestorOut:
    profile = await _own_profile(db, user)
    return InvestorOut.model_validate(profile)


@router.patch("/me", response_model=InvestorOut)
async def update_me(payload: InvestorUpdate, db: DbDep, user: InvestorUser) -> InvestorOut:
    profile = await _own_profile(db, user)
    updated = await investor_service.update(db, profile=profile, payload=payload)
    return InvestorOut.model_validate(updated)


@router.get("/me/matches", response_model=Page[MatchWithProject])
async def my_matches(
    db: DbDep, user: InvestorUser, page: PaginationDep
) -> Page[MatchWithProject]:
    profile = await _own_profile(db, user)
    rows = await investor_service.list_matches(db, investor_id=profile.id, page=page)
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    return Page[MatchWithProject](
        items=[MatchWithProject.model_validate(m) for m in items],
        next_cursor=str(items[-1].id) if has_more and items else None,
        has_more=has_more,
    )


@router.get("/me/notifications", response_model=Page[NotificationOut])
async def my_notifications(
    db: DbDep, user: CurrentUser, page: PaginationDep
) -> Page[NotificationOut]:
    rows = await notification_service.list_for_user(db, user.id, page)
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    return Page[NotificationOut](
        items=[NotificationOut.model_validate(n) for n in items],
        next_cursor=str(items[-1].id) if has_more and items else None,
        has_more=has_more,
    )


@router.patch("/me/notifications/{notification_id}", response_model=NotificationOut)
async def mark_notification(
    notification_id: str, payload: NotificationReadUpdate, db: DbDep, user: CurrentUser
) -> NotificationOut:
    import uuid

    n = await notification_service.mark_read(
        db, notification_id=uuid.UUID(notification_id), user_id=user.id, is_read=payload.is_read
    )
    if n is None:
        raise NotFoundError("Notification not found.")
    return NotificationOut.model_validate(n)


@router.post("/me/documents", response_model=PresignUploadResponse)
async def presign_document(
    payload: PresignUploadRequest, db: DbDep, user: InvestorUser
) -> PresignUploadResponse:
    profile = await _own_profile(db, user)
    storage.validate_upload(payload.content_type)
    key = storage.build_key(prefix="investor", owner_id=profile.id, filename=payload.filename)
    url = storage.presign_put(key, payload.content_type)
    await investor_service.add_document(
        db,
        profile=profile,
        doc={
            "type": payload.doc_type,
            "r2_key": key,
            "filename": payload.filename,
            "content_type": payload.content_type,
        },
    )
    from app.core.config import settings

    return PresignUploadResponse(
        upload_url=url, r2_key=key, expires_in=settings.R2_PRESIGN_EXPIRY_SECONDS
    )


@router.delete("/me/documents/{r2_key:path}", response_model=MessageResponse)
async def delete_document(r2_key: str, db: DbDep, user: InvestorUser) -> MessageResponse:
    profile = await _own_profile(db, user)
    storage.delete_object(r2_key)
    await investor_service.remove_document(db, profile=profile, r2_key=r2_key)
    return MessageResponse(message="Document deleted.")
