"""Phase 2 endpoints (PRD §6.6, §6.8, §11).

Routed and documented in OpenAPI so the API surface is stable, but guarded by
the ``FEATURE_PHASE2`` flag — they return 501 until the feature is enabled and
the handlers are implemented.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.config import settings
from app.core.exceptions import NotImplementedFeatureError

router = APIRouter(tags=["phase2"])


def _guard() -> None:
    raise NotImplementedFeatureError(
        "This feature ships in Phase 2 and is not yet enabled."
        if not settings.FEATURE_PHASE2
        else "This endpoint is not implemented yet."
    )


# ── Matches: interest / dismiss / deal-room / DD / confidential ──
@router.post("/matches/{match_id}/interest")
async def express_interest(match_id: uuid.UUID) -> None:
    _guard()


@router.post("/matches/{match_id}/dismiss")
async def dismiss_match(match_id: uuid.UUID) -> None:
    _guard()


@router.get("/matches/{match_id}/deal-room")
async def deal_room(match_id: uuid.UUID) -> None:
    _guard()


@router.post("/matches/{match_id}/due-diligence")
async def request_due_diligence(match_id: uuid.UUID) -> None:
    _guard()


@router.patch("/matches/{match_id}/confidential")
async def toggle_confidential(match_id: uuid.UUID) -> None:
    _guard()


# ── Due diligence ──
@router.get("/due-diligence/{dd_id}")
async def get_due_diligence(dd_id: uuid.UUID) -> None:
    _guard()


@router.post("/due-diligence/{dd_id}/items/{item_id}")
async def upload_dd_item(dd_id: uuid.UUID, item_id: str) -> None:
    _guard()


@router.patch("/due-diligence/{dd_id}/items/{item_id}")
async def update_dd_item(dd_id: uuid.UUID, item_id: str) -> None:
    _guard()


# ── Milestones (monitoring dashboard) ──
@router.get("/projects/{project_id}/milestones")
async def list_milestones(project_id: uuid.UUID) -> None:
    _guard()


@router.post("/projects/{project_id}/milestones")
async def create_milestone(project_id: uuid.UUID) -> None:
    _guard()


@router.patch("/milestones/{milestone_id}")
async def update_milestone(milestone_id: uuid.UUID) -> None:
    _guard()
