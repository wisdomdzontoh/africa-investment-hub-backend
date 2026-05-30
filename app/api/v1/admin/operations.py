"""Admin operational endpoints — investors, projects, consultants, users,
matches, audit log, analytics (PRD §6.4, §11)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbDep, PaginationDep
from app.core.clerk_client import update_user_public_metadata
from app.models.audit import AuditLog
from app.models.enums import (
    MatchStatus,
    ProjectStatus,
    UserStatus,
)
from app.models.match import Match
from app.models.project import Project
from app.models.user import User
from app.schemas.admin import AnalyticsOverview, AuditLogOut
from app.schemas.investor import InvestorAdminOut
from app.schemas.match import (
    AdminStatusUpdate,
    MatchCreate,
    MatchOut,
    MatchStatusUpdate,
)
from app.schemas.project import ProjectAdminOut
from app.schemas.user import UserOut, UserRoleUpdate, UserStatusUpdate
from app.services import (
    admin_service,
    audit_service,
    investor_service,
    match_service,
)
from app.services.user_service import get_by_id

router = APIRouter(tags=["admin"])


def _page(rows: list, page: PaginationDep, schema) -> dict:
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    return {
        "items": [schema.model_validate(r) for r in items],
        "next_cursor": str(items[-1].id) if has_more and items else None,
        "has_more": has_more,
    }


# ─────────────────────────── Investors ───────────────────────────
@router.get("/investors")
async def list_investors(
    db: DbDep,
    _: AdminUser,
    page: PaginationDep,
    status: Annotated[UserStatus | None, Query()] = None,
) -> dict:
    rows = await admin_service.list_investors(db, status=status, page=page)
    # Attach account status from the joined user for the admin view.
    out = []
    for profile in rows[: page.limit]:
        user = await get_by_id(db, profile.user_id)
        data = InvestorAdminOut.model_validate(profile).model_copy(
            update={"status": user.status if user else UserStatus.pending}
        )
        out.append(data)
    has_more = len(rows) > page.limit
    return {
        "items": out,
        "next_cursor": str(rows[page.limit - 1].id) if has_more else None,
        "has_more": has_more,
    }


@router.get("/investors/{investor_id}", response_model=InvestorAdminOut)
async def get_investor(investor_id: uuid.UUID, db: DbDep, _: AdminUser) -> InvestorAdminOut:
    profile = await investor_service.get_or_404(db, investor_id)
    user = await get_by_id(db, profile.user_id)
    return InvestorAdminOut.model_validate(profile).model_copy(
        update={"status": user.status if user else UserStatus.pending}
    )


@router.patch("/investors/{investor_id}/status", response_model=InvestorAdminOut)
async def set_investor_status(
    investor_id: uuid.UUID, payload: AdminStatusUpdate, db: DbDep, admin: AdminUser
) -> InvestorAdminOut:
    profile = await admin_service.set_investor_status(
        db, investor_id=investor_id, action=payload.action, reason=payload.reason, actor_id=admin.id
    )
    user = await get_by_id(db, profile.user_id)
    return InvestorAdminOut.model_validate(profile).model_copy(
        update={"status": user.status if user else UserStatus.pending}
    )


@router.get("/investors.csv", response_class=PlainTextResponse)
async def export_investors(db: DbDep, _: AdminUser) -> PlainTextResponse:
    return PlainTextResponse(
        await admin_service.export_investors_csv(db), media_type="text/csv"
    )


# ─────────────────────────── Projects ───────────────────────────
@router.get("/projects")
async def list_projects(
    db: DbDep,
    _: AdminUser,
    page: PaginationDep,
    status: Annotated[ProjectStatus | None, Query()] = None,
) -> dict:
    rows = await admin_service.list_projects(db, status=status, page=page)
    return _page(rows, page, ProjectAdminOut)


@router.get("/projects/{project_id}", response_model=ProjectAdminOut)
async def get_project(project_id: uuid.UUID, db: DbDep, _: AdminUser) -> ProjectAdminOut:
    project = await db.get(Project, project_id)
    if project is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Project not found.")
    return ProjectAdminOut.model_validate(project)


@router.patch("/projects/{project_id}/status", response_model=ProjectAdminOut)
async def set_project_status(
    project_id: uuid.UUID, payload: AdminStatusUpdate, db: DbDep, admin: AdminUser
) -> ProjectAdminOut:
    project = await admin_service.set_project_status(
        db,
        project_id=project_id,
        action=payload.action,
        reason=payload.reason,
        risk_level=payload.risk_level,
        actor_id=admin.id,
    )
    return ProjectAdminOut.model_validate(project)


@router.get("/projects.csv", response_class=PlainTextResponse)
async def export_projects(db: DbDep, _: AdminUser) -> PlainTextResponse:
    return PlainTextResponse(
        await admin_service.export_projects_csv(db), media_type="text/csv"
    )


# ─────────────────────────── Users ───────────────────────────
@router.get("/users")
async def list_users(db: DbDep, _: AdminUser, page: PaginationDep) -> dict:
    rows = await admin_service.list_users(db, page=page)
    return _page(rows, page, UserOut)


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: uuid.UUID, payload: UserRoleUpdate, db: DbDep, admin: AdminUser
) -> UserOut:
    user = await get_by_id(db, user_id)
    if user is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("User not found.")
    user.role = payload.role
    await db.flush()
    await update_user_public_metadata(user.clerk_id, {"role": payload.role.value})
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="user.role_changed",
        target_type="user",
        target_id=user.id,
        metadata={"role": payload.role.value},
    )
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}/status", response_model=UserOut)
async def update_user_status(
    user_id: uuid.UUID, payload: UserStatusUpdate, db: DbDep, admin: AdminUser
) -> UserOut:
    user = await get_by_id(db, user_id)
    if user is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("User not found.")
    user.status = payload.status
    await db.flush()
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="user.status_changed",
        target_type="user",
        target_id=user.id,
        metadata={"status": payload.status.value},
    )
    return UserOut.model_validate(user)


# ─────────────────────────── Matches ───────────────────────────
@router.get("/matches")
async def list_matches(
    db: DbDep,
    _: AdminUser,
    page: PaginationDep,
    status: Annotated[MatchStatus | None, Query()] = None,
) -> dict:
    rows = await match_service.list_all(db, status=status, page=page)
    return _page(rows, page, MatchOut)


@router.post("/matches", response_model=MatchOut, status_code=201)
async def create_match(payload: MatchCreate, db: DbDep, admin: AdminUser) -> MatchOut:
    match = await match_service.create_manual(
        db,
        investor_id=payload.investor_id,
        project_id=payload.project_id,
        explanation=payload.explanation,
    )
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="match.created_manual",
        target_type="match",
        target_id=match.id,
    )
    return MatchOut.model_validate(match)


@router.patch("/matches/{match_id}/status", response_model=MatchOut)
async def update_match_status(
    match_id: uuid.UUID, payload: MatchStatusUpdate, db: DbDep, admin: AdminUser
) -> MatchOut:
    match = await match_service.get_or_404(db, match_id)
    updated = await match_service.update_status(db, match=match, status=payload.status)
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="match.status_changed",
        target_type="match",
        target_id=match.id,
        metadata={"status": payload.status.value},
    )
    return MatchOut.model_validate(updated)


# ─────────────────────────── Audit log ───────────────────────────
@router.get("/audit-log")
async def audit_log(db: DbDep, _: AdminUser, page: PaginationDep) -> dict:
    from sqlalchemy import select as _select

    stmt = _select(AuditLog).order_by(AuditLog.created_at.desc()).limit(page.limit + 1)
    if page.cursor is not None:
        stmt = stmt.where(AuditLog.id != page.cursor)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    has_more = len(rows) > page.limit
    items = rows[: page.limit]
    return {
        "items": [AuditLogOut.model_validate(r) for r in items],
        "next_cursor": str(items[-1].id) if has_more and items else None,
        "has_more": has_more,
    }


# ─────────────────────────── Analytics ───────────────────────────
@router.get("/analytics", response_model=AnalyticsOverview)
async def analytics(db: DbDep, _: AdminUser) -> AnalyticsOverview:
    investors_by_status = await admin_service.count_by(db, User, User.status)
    projects_by_status = await admin_service.count_by(db, Project, Project.status)
    projects_by_sector = await admin_service.count_by(db, Project, Project.sector)
    matches_by_status = await admin_service.count_by(db, Match, Match.status)
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    return AnalyticsOverview(
        investors_by_status=investors_by_status,
        projects_by_status=projects_by_status,
        projects_by_sector=projects_by_sector,
        matches_by_status=matches_by_status,
        total_users=total_users,
    )
