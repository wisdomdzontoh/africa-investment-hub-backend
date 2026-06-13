"""Investor-facing match actions (PRD §6.7, §12.3).

Express interest / dismiss / confidential-mode toggle on the investor's own
matches. The brokered NDA→MOU→close pipeline stays with the admin/legal flow
(``admin/operations.py``); these endpoints only cover the investor's choices.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbDep, require_investor
from app.core.exceptions import NotFoundError
from app.models.user import User
from app.schemas.match import ConfidentialUpdate, MatchOut
from app.services import audit_service, investor_service, match_service

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
