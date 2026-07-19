"""Milestone service — project monitoring (PRD §6.6).

Access model:
  - the project's facilitator (owner) and admins manage milestones;
  - an engaged investor (holds a non-dismissed match for the project) may view
    them to monitor progress.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.enums import MatchStatus, UserRole
from app.models.investor import InvestorProfile
from app.models.match import Match
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.user import User
from app.schemas.milestone import MilestoneCreate, MilestoneUpdate

_INVESTOR_HIDDEN = frozenset({MatchStatus.ai_recommended, MatchStatus.dismissed})


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    return project


async def _investor_is_engaged(
    db: AsyncSession, *, user: User, project_id: uuid.UUID
) -> bool:
    """True if the investor holds a visible (non-dismissed) match for the project."""
    result = await db.execute(
        select(Match.status)
        .join(InvestorProfile, InvestorProfile.id == Match.investor_id)
        .where(InvestorProfile.user_id == user.id, Match.project_id == project_id)
    )
    return any(status not in _INVESTOR_HIDDEN for status in result.scalars().all())


async def assert_can_view(db: AsyncSession, *, project: Project, user: User) -> None:
    if user.role == UserRole.admin or project.owner_user_id == user.id:
        return
    if user.role == UserRole.investor and await _investor_is_engaged(
        db, user=user, project_id=project.id
    ):
        return
    raise ForbiddenError("You don't have access to this project's milestones.")


def _assert_can_manage(project: Project, user: User) -> None:
    if user.role != UserRole.admin and project.owner_user_id != user.id:
        raise ForbiddenError("Only the project facilitator can manage milestones.")


async def list_for_project(
    db: AsyncSession, *, project_id: uuid.UUID, user: User
) -> list[Milestone]:
    project = await _get_project_or_404(db, project_id)
    await assert_can_view(db, project=project, user=user)
    result = await db.execute(
        select(Milestone)
        .where(Milestone.project_id == project_id)
        .order_by(Milestone.due_date.asc().nullslast(), Milestone.created_at.asc())
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession, *, project_id: uuid.UUID, payload: MilestoneCreate, user: User
) -> Milestone:
    project = await _get_project_or_404(db, project_id)
    _assert_can_manage(project, user)
    milestone = Milestone(project_id=project_id, **payload.model_dump())
    db.add(milestone)
    await db.flush()
    return milestone


async def _get_owned_or_404(
    db: AsyncSession, *, milestone_id: uuid.UUID, user: User
) -> Milestone:
    milestone = await db.get(Milestone, milestone_id)
    if milestone is None:
        raise NotFoundError("Milestone not found.")
    project = await _get_project_or_404(db, milestone.project_id)
    _assert_can_manage(project, user)
    return milestone


async def update(
    db: AsyncSession, *, milestone_id: uuid.UUID, payload: MilestoneUpdate, user: User
) -> Milestone:
    milestone = await _get_owned_or_404(db, milestone_id=milestone_id, user=user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(milestone, field, value)
    await db.flush()
    return milestone


async def delete(db: AsyncSession, *, milestone_id: uuid.UUID, user: User) -> None:
    milestone = await _get_owned_or_404(db, milestone_id=milestone_id, user=user)
    await db.delete(milestone)
    await db.flush()
