"""Project service (PRD §6.3) including the NDA gate (§6.10, §14).

The NDA gate is enforced here — never in the route, never on the frontend.
``full_description`` and deal-room documents are only exposed when the calling
investor holds a match for the project at status ``nda_signed`` or beyond.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.enums import (
    NDA_UNLOCKED_STATUSES,
    ProjectStatus,
    UserRole,
    UserStatus,
)
from app.models.investor import InvestorProfile
from app.models.match import Match
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.workers.queue import enqueue


# ─────────────────────────── Public listing ───────────────────────────
ProjectFilters = dict[str, Any]


def _apply_filters(stmt: Select[Any], f: ProjectFilters) -> Select[Any]:
    if f.get("sector"):
        stmt = stmt.where(Project.sector.in_(f["sector"]))
    if f.get("country"):
        stmt = stmt.where(Project.country.in_(f["country"]))
    if f.get("min_funding") is not None:
        stmt = stmt.where(Project.funding_required >= Decimal(str(f["min_funding"])))
    if f.get("max_funding") is not None:
        stmt = stmt.where(Project.funding_required <= Decimal(str(f["max_funding"])))
    if f.get("risk_level"):
        stmt = stmt.where(Project.risk_level == f["risk_level"])
    if f.get("stage"):
        stmt = stmt.where(Project.project_stage == f["stage"])
    if f.get("funding_type"):
        stmt = stmt.where(Project.funding_type == f["funding_type"])
    return stmt


def _apply_sort(stmt: Select[Any], sort: str | None) -> Select[Any]:
    if sort == "highest_roi":
        return stmt.order_by(Project.expected_roi_max.desc().nullslast(), Project.id.desc())
    if sort == "lowest_risk":
        return stmt.order_by(Project.risk_level.asc().nullsfirst(), Project.id.desc())
    if sort == "most_viewed":
        return stmt.order_by(Project.view_count.desc(), Project.id.desc())
    # Default: newest first.
    return stmt.order_by(Project.created_at.desc(), Project.id.desc())


async def list_public(
    db: AsyncSession, *, filters: ProjectFilters, sort: str | None, page: Pagination
) -> list[Project]:
    stmt = select(Project).where(Project.status == ProjectStatus.approved)
    stmt = _apply_filters(stmt, filters)
    stmt = _apply_sort(stmt, sort)
    stmt = stmt.limit(page.limit + 1)
    if page.cursor is not None:
        anchor = await db.get(Project, page.cursor)
        if anchor is not None:
            stmt = stmt.where(Project.created_at < anchor.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ─────────────────────────── NDA gate ───────────────────────────
async def investor_has_nda_access(
    db: AsyncSession, *, investor_id: uuid.UUID, project_id: uuid.UUID
) -> bool:
    """True iff the investor's match for this project is NDA-signed or beyond."""
    result = await db.execute(
        select(Match.status).where(
            Match.investor_id == investor_id, Match.project_id == project_id
        )
    )
    status = result.scalar_one_or_none()
    return status in NDA_UNLOCKED_STATUSES


async def get_detail(
    db: AsyncSession, *, project_id: uuid.UUID, user: User | None
) -> tuple[Project, dict[str, bool]]:
    """Return an approved project plus a visibility map for gated fields.

    Visibility rules (PRD §6.1, §6.10):
      - executive_summary: approved investors / owner / admin
      - full_description : only when the investor holds an NDA-signed match
    """
    project = await db.get(Project, project_id)
    if project is None or project.status != ProjectStatus.approved:
        # Owners and admins may view their own non-approved projects elsewhere.
        if project is None or user is None or (
            user.role != UserRole.admin and project.owner_user_id != user.id
        ):
            raise NotFoundError("Project not found.")

    is_owner = user is not None and project.owner_user_id == user.id
    is_admin = user is not None and user.role == UserRole.admin
    is_approved_investor = (
        user is not None
        and user.role == UserRole.investor
        and user.status == UserStatus.approved
    )

    show_summary = is_owner or is_admin or is_approved_investor
    show_full = is_owner or is_admin
    if not show_full and is_approved_investor and user is not None:
        investor = await db.execute(
            select(InvestorProfile.id).where(InvestorProfile.user_id == user.id)
        )
        investor_id = investor.scalar_one_or_none()
        if investor_id is not None:
            show_full = await investor_has_nda_access(
                db, investor_id=investor_id, project_id=project_id
            )

    return project, {"executive_summary": show_summary, "full_description": show_full}


async def increment_view(db: AsyncSession, project: Project) -> None:
    project.view_count += 1
    await db.flush()


# ─────────────────────────── Owner operations ───────────────────────────
async def create(db: AsyncSession, *, owner: User, payload: ProjectCreate) -> Project:
    project = Project(
        owner_user_id=owner.id,
        status=ProjectStatus.pending,
        **payload.model_dump(),
    )
    db.add(project)
    await db.flush()
    await enqueue("embed_project", str(project.id))
    return project


async def list_own(
    db: AsyncSession, *, owner_id: uuid.UUID, page: Pagination
) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.owner_user_id == owner_id)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .limit(page.limit + 1)
    )
    if page.cursor is not None:
        stmt = stmt.where(Project.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_owned_or_404(
    db: AsyncSession, *, project_id: uuid.UUID, owner_id: uuid.UUID
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    if project.owner_user_id != owner_id:
        raise ForbiddenError("You do not own this project.")
    return project


async def update(
    db: AsyncSession, *, project: Project, payload: ProjectUpdate
) -> Project:
    changed = payload.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(project, field, value)
    await db.flush()
    # Re-embed if any descriptive field changed.
    if changed.keys() & {"title", "brief_description", "executive_summary", "sector"}:
        await enqueue("embed_project", str(project.id))
    return project


async def add_document(
    db: AsyncSession, *, project: Project, doc: dict[str, Any]
) -> Project:
    doc.setdefault("uploaded_at", datetime.now(UTC).isoformat())
    project.documents = [*project.documents, doc]
    await db.flush()
    return project


async def remove_document(db: AsyncSession, *, project: Project, r2_key: str) -> Project:
    project.documents = [d for d in project.documents if d.get("r2_key") != r2_key]
    await db.flush()
    return project
