"""Admin operational endpoints — investors, projects, consultants, users,
matches, audit log, analytics (PRD §6.4, §11)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbDep, PaginationDep
from app.core import clerk_client
from app.core.clerk_client import update_user_public_metadata
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.enums import (
    MatchStatus,
    ProjectStatus,
    UserStatus,
)
from app.models.match import Match
from app.models.project import Project
from app.models.user import User
from app.schemas.admin import AnalyticsOverview, AuditLogOut, RiskAssessmentOut
from app.schemas.common import DocumentUrlResponse, MessageResponse
from app.schemas.investor import InvestorAdminOut
from app.schemas.match import (
    AdminMatchOut,
    AdminStatusUpdate,
    MatchCreate,
    MatchOut,
    MatchStatusUpdate,
)
from app.schemas.project import ProjectAdminOut, ProjectCreate
from app.schemas.user import AdminInvite, UserOut, UserRoleUpdate, UserStatusUpdate
from app.services import (
    admin_service,
    audit_service,
    investor_service,
    match_service,
    project_service,
    storage,
)
from app.services.ai import risk as risk_service
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


@router.get(
    "/investors/{investor_id}/documents/{r2_key:path}", response_model=DocumentUrlResponse
)
async def download_investor_document(
    investor_id: uuid.UUID, r2_key: str, db: DbDep, admin: AdminUser
) -> DocumentUrlResponse:
    """Short-lived download URL for an investor's uploaded document (admin)."""
    profile = await investor_service.get_or_404(db, investor_id)
    if not any(d.get("r2_key") == r2_key for d in profile.documents):
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Document not found.")
    url = storage.presign_get(r2_key, accessor_id=admin.id)
    return DocumentUrlResponse(url=url, expires_in=settings.R2_PRESIGN_EXPIRY_SECONDS)


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


@router.post("/projects", response_model=ProjectAdminOut, status_code=201)
async def create_project(
    payload: ProjectCreate, db: DbDep, admin: AdminUser
) -> ProjectAdminOut:
    """Admin-curated project listing. Created as ``pending`` and owned by the
    admin; it goes through the normal review queue before going live."""
    project = await project_service.create(db, owner=admin, payload=payload)
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="project.created_by_admin",
        target_type="project",
        target_id=project.id,
    )
    return ProjectAdminOut.model_validate(project)


@router.post("/projects/{project_id}/risk-assessment", response_model=RiskAssessmentOut)
async def run_risk_assessment(
    project_id: uuid.UUID, db: DbDep, admin: AdminUser
) -> RiskAssessmentOut:
    """Generate an advisory AI risk assessment and append it to admin notes.
    The admin still sets the final ``risk_level`` on approval (PRD §12.5)."""
    project = await db.get(Project, project_id)
    if project is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Project not found.")
    assessment = await risk_service.assess(db, project_id)
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="project.risk_assessed",
        target_type="project",
        target_id=project_id,
    )
    await db.refresh(project)
    return RiskAssessmentOut(assessment=assessment, admin_notes=project.admin_notes)


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


@router.post("/users/invite", response_model=MessageResponse, status_code=202)
async def invite_admin(
    payload: AdminInvite, db: DbDep, admin: AdminUser
) -> MessageResponse:
    """Invite a new administrator. Only the ``admin`` role can be provisioned
    this way — investors and facilitators self-register. Clerk emails the
    invite; the webhook creates the local admin user on sign-up."""
    await clerk_client.create_invitation(email=payload.email, role="admin")
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="user.admin_invited",
        target_type="user",
        metadata={"email": payload.email},
    )
    return MessageResponse(message="Invitation sent.")


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
    from app.core.exceptions import ForbiddenError, NotFoundError

    if user_id == admin.id:
        raise ForbiddenError("You cannot change your own account status.")
    user = await get_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    previous = user.status
    user.status = payload.status
    await db.flush()

    # Mirror suspension into Clerk (ban blocks sign-in at the identity plane;
    # our per-request status check remains the enforcement point).
    if payload.status == UserStatus.suspended and previous != UserStatus.suspended:
        await clerk_client.ban_user(user.clerk_id)
    elif previous == UserStatus.suspended and payload.status != UserStatus.suspended:
        await clerk_client.unban_user(user.clerk_id)

    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="user.status_changed",
        target_type="user",
        target_id=user.id,
        metadata={"from": previous.value, "status": payload.status.value},
    )
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(user_id: uuid.UUID, db: DbDep, admin: AdminUser) -> MessageResponse:
    """Soft-delete a user and delete their Clerk identity (PRD §6.4).

    Hard deletion (DB purge + document cleanup) happens 30 days later via the
    scheduled purge job, mirroring the self-serve ``DELETE /account`` flow."""
    from app.core.exceptions import ForbiddenError, NotFoundError
    from app.services import user_service

    if user_id == admin.id:
        raise ForbiddenError("You cannot delete your own account from the admin panel.")
    user = await get_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User not found.")

    await user_service.soft_delete(db, user)
    clerk_deleted = await clerk_client.delete_user(user.clerk_id)
    await audit_service.record(
        db,
        actor_user_id=admin.id,
        action="user.deleted",
        target_type="user",
        target_id=user.id,
        metadata={"clerk_deleted": clerk_deleted, "email": user.email},
    )
    return MessageResponse(message="User deactivated; permanent deletion in 30 days.")


# ─────────────────────────── Matches ───────────────────────────
@router.get("/matches")
async def list_matches(
    db: DbDep,
    _: AdminUser,
    page: PaginationDep,
    status: Annotated[MatchStatus | None, Query()] = None,
) -> dict:
    rows = await match_service.list_all(db, status=status, page=page)
    items = rows[: page.limit]
    # Enrich with human-readable project / investor names for the admin list.
    out = []
    for m in items:
        project = await db.get(Project, m.project_id)
        investor = await investor_service.get(db, m.investor_id)
        out.append(
            AdminMatchOut.model_validate(m).model_copy(
                update={
                    "project_title": project.title if project else None,
                    "investor_company": investor.company_name if investor else None,
                }
            )
        )
    has_more = len(rows) > page.limit
    return {
        "items": out,
        "next_cursor": str(items[-1].id) if has_more and items else None,
        "has_more": has_more,
    }


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
    from app.models.enums import UserRole

    # Role-filtered: an admin or facilitator account must never be counted
    # as an investor (this was the source of mismatched dashboard figures).
    investors_by_status = await admin_service.count_by(
        db, User, User.status, where=(User.role == UserRole.investor)
    )
    users_by_role = await admin_service.count_by(db, User, User.role)
    projects_by_status = await admin_service.count_by(db, Project, Project.status)
    projects_by_sector = await admin_service.count_by(db, Project, Project.sector)
    matches_by_status = await admin_service.count_by(db, Match, Match.status)
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    total_matches = (await db.execute(select(func.count()).select_from(Match))).scalar() or 0
    avg_match_score = (await db.execute(select(func.avg(Match.score)))).scalar()
    return AnalyticsOverview(
        investors_by_status=investors_by_status,
        users_by_role=users_by_role,
        projects_by_status=projects_by_status,
        projects_by_sector=projects_by_sector,
        matches_by_status=matches_by_status,
        total_users=total_users,
        total_matches=total_matches,
        avg_match_score=float(avg_match_score) if avg_match_score is not None else None,
    )
