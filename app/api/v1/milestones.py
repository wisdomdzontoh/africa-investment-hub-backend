"""Project monitoring — milestones (PRD §6.6, P2-06).

The facilitator (owner) and admins manage milestones; engaged investors view
them. Routes span ``/projects/{id}/milestones`` (collection) and
``/milestones/{id}`` (item), so the router carries no prefix.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbDep
from app.schemas.common import MessageResponse
from app.schemas.milestone import MilestoneCreate, MilestoneOut, MilestoneUpdate
from app.services import milestone_service

router = APIRouter(tags=["milestones"])


@router.get("/projects/{project_id}/milestones", response_model=list[MilestoneOut])
async def list_milestones(
    project_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> list[MilestoneOut]:
    rows = await milestone_service.list_for_project(db, project_id=project_id, user=user)
    return [MilestoneOut.model_validate(m) for m in rows]


@router.post(
    "/projects/{project_id}/milestones", response_model=MilestoneOut, status_code=201
)
async def create_milestone(
    project_id: uuid.UUID, payload: MilestoneCreate, db: DbDep, user: CurrentUser
) -> MilestoneOut:
    milestone = await milestone_service.create(
        db, project_id=project_id, payload=payload, user=user
    )
    return MilestoneOut.model_validate(milestone)


@router.patch("/milestones/{milestone_id}", response_model=MilestoneOut)
async def update_milestone(
    milestone_id: uuid.UUID, payload: MilestoneUpdate, db: DbDep, user: CurrentUser
) -> MilestoneOut:
    milestone = await milestone_service.update(
        db, milestone_id=milestone_id, payload=payload, user=user
    )
    return MilestoneOut.model_validate(milestone)


@router.delete("/milestones/{milestone_id}", response_model=MessageResponse)
async def delete_milestone(
    milestone_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> MessageResponse:
    await milestone_service.delete(db, milestone_id=milestone_id, user=user)
    return MessageResponse(message="Milestone deleted.")
