"""Investor-facing match actions (PRD §6.7, §12.3).

Express interest / dismiss / confidential-mode toggle on the investor's own
matches. The brokered NDA→MOU→close pipeline stays with the admin/legal flow
(``admin/operations.py``); these endpoints only cover the investor's choices.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, DbDep, require_investor
from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.enums import MATCH_PIPELINE_ORDER, MatchStatus
from app.models.investor import InvestorProfile
from app.models.user import User
from app.schemas.match import (
    ConfidentialUpdate,
    DealDocumentUrl,
    DealRoomOut,
    DealRoomProject,
    MatchOut,
)
from app.services import (
    audit_service,
    investor_service,
    match_service,
    pdf_service,
    project_service,
    storage,
)

router = APIRouter(prefix="/matches", tags=["matches"])

InvestorUser = Annotated[User, Depends(require_investor)]


async def _owned_match(db: DbDep, match_id: uuid.UUID, user: User):
    profile = await investor_service.get_by_user(db, user.id)
    if profile is None:
        raise NotFoundError("Investor profile not found. Complete registration first.")
    return await match_service.get_owned_or_403(db, match_id=match_id, investor_id=profile.id)


@router.post("/{match_id}/interest", response_model=MatchOut)
async def express_interest(match_id: uuid.UUID, db: DbDep, user: InvestorUser) -> MatchOut:
    match = await _owned_match(db, match_id, user)
    updated = await match_service.express_interest(db, match=match)
    await audit_service.record(
        db,
        actor_user_id=user.id,
        action="match.investor_interested",
        target_type="match",
        target_id=match.id,
    )
    return MatchOut.model_validate(updated)


@router.post("/{match_id}/dismiss", response_model=MatchOut)
async def dismiss_match(match_id: uuid.UUID, db: DbDep, user: InvestorUser) -> MatchOut:
    match = await _owned_match(db, match_id, user)
    updated = await match_service.dismiss(db, match=match)
    await audit_service.record(
        db,
        actor_user_id=user.id,
        action="match.dismissed",
        target_type="match",
        target_id=match.id,
    )
    return MatchOut.model_validate(updated)


@router.patch("/{match_id}/confidential", response_model=MatchOut)
async def toggle_confidential(
    match_id: uuid.UUID, payload: ConfidentialUpdate, db: DbDep, user: InvestorUser
) -> MatchOut:
    match = await _owned_match(db, match_id, user)
    updated = await match_service.set_confidential(db, match=match, value=payload.confidential)
    return MatchOut.model_validate(updated)


# ─────────────────────────── Deal room (P2-04) ───────────────────────────
@router.post("/{match_id}/nda/sign", response_model=MatchOut)
async def sign_nda(match_id: uuid.UUID, db: DbDep, user: InvestorUser) -> MatchOut:
    match = await _owned_match(db, match_id, user)
    updated = await match_service.sign_nda(db, match=match)
    await audit_service.record(
        db,
        actor_user_id=user.id,
        action="match.nda_signed",
        target_type="match",
        target_id=match.id,
    )
    return MatchOut.model_validate(updated)


@router.get("/{match_id}/deal-room", response_model=DealRoomOut)
async def deal_room(match_id: uuid.UUID, db: DbDep, user: CurrentUser) -> DealRoomOut:
    match = await match_service.get_accessible_match(db, match_id=match_id, user=user)
    project, unlocked = await match_service.deal_room_view(db, match=match, user=user)

    project_out = DealRoomProject.model_validate(project)
    # Apply the NDA gate: privileged fields are blanked unless unlocked.
    if not unlocked:
        project_out.full_description = None
        project_out.documents = []
    return DealRoomOut(
        match=MatchOut.model_validate(match),
        project=project_out,
        nda_unlocked=unlocked,
        can_sign_nda=match.status == MatchStatus.nda_sent,
    )


async def _deal_pdf_context(db: DbDep, match_id: uuid.UUID, user):
    match = await match_service.get_accessible_match(db, match_id=match_id, user=user)
    project = await project_service.get(db, match.project_id)
    investor = await db.get(InvestorProfile, match.investor_id)
    if project is None or investor is None:
        raise NotFoundError("Deal documents are unavailable for this match.")
    return match, project, investor


@router.get("/{match_id}/nda.pdf")
async def nda_pdf(match_id: uuid.UUID, db: DbDep, user: CurrentUser) -> Response:
    """Render the NDA as a PDF for review/records (parties + admin)."""
    _, project, investor = await _deal_pdf_context(db, match_id, user)
    pdf = pdf_service.render_nda(project=project, investor=investor)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="nda.pdf"'},
    )


@router.get("/{match_id}/mou.pdf")
async def mou_pdf(match_id: uuid.UUID, db: DbDep, user: CurrentUser) -> Response:
    """Render the MOU as a PDF — only once the deal reaches the MOU stage."""
    match, project, investor = await _deal_pdf_context(db, match_id, user)
    if MATCH_PIPELINE_ORDER.get(match.status, 0) < MATCH_PIPELINE_ORDER[MatchStatus.mou_drafted]:
        raise ForbiddenError("The MOU isn't available at this stage.")
    pdf = pdf_service.render_mou(project=project, investor=investor)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="mou.pdf"'},
    )


@router.get("/{match_id}/documents/{r2_key:path}", response_model=DealDocumentUrl)
async def deal_room_document(
    match_id: uuid.UUID, r2_key: str, db: DbDep, user: CurrentUser
) -> DealDocumentUrl:
    """Short-lived presigned download for a deal-room document — NDA-gated."""
    match = await match_service.get_accessible_match(db, match_id=match_id, user=user)
    project, unlocked = await match_service.deal_room_view(db, match=match, user=user)
    if not unlocked:
        raise ForbiddenError("Sign the NDA to access deal-room documents.")
    # The key must belong to this project's document set.
    if not any(doc.get("r2_key") == r2_key for doc in project.documents):
        raise NotFoundError("Document not found in this deal room.")
    url = storage.presign_get(r2_key, accessor_id=user.id)
    return DealDocumentUrl(url=url, expires_in=settings.R2_PRESIGN_EXPIRY_SECONDS)
