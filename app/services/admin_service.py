"""Admin operational service — status transitions, listings, CSV export
(PRD §6.4, §14). Every mutating action writes an audit-log entry.
"""

from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.exceptions import NotFoundError, ValidationError
from app.models.consultant import ConsultantProfile
from app.models.enums import (
    ConsultantStatus,
    ProjectStatus,
    RiskLevel,
    UserStatus,
)
from app.models.investor import InvestorProfile
from app.models.project import Project
from app.models.user import User
from app.services import audit_service, notification_service
from app.workers.queue import enqueue


# ─────────────────────── Investor administration ───────────────────────
async def _investor_with_user(
    db: AsyncSession, investor_id: uuid.UUID
) -> tuple[InvestorProfile, User]:
    profile = await db.get(InvestorProfile, investor_id)
    if profile is None:
        raise NotFoundError("Investor not found.")
    user = await db.get(User, profile.user_id)
    if user is None:
        raise NotFoundError("Investor account not found.")
    return profile, user


_STATUS_ACTIONS = {
    "approve": UserStatus.approved,
    "reject": UserStatus.rejected,
    "suspend": UserStatus.suspended,
    "request_info": UserStatus.pending,
}


async def set_investor_status(
    db: AsyncSession,
    *,
    investor_id: uuid.UUID,
    action: str,
    reason: str | None,
    actor_id: uuid.UUID,
) -> InvestorProfile:
    if action not in _STATUS_ACTIONS:
        raise ValidationError(f"Unknown action: {action}")
    profile, user = await _investor_with_user(db, investor_id)
    previous = user.status
    user.status = _STATUS_ACTIONS[action]
    await db.flush()

    await audit_service.record(
        db,
        actor_user_id=actor_id,
        action=f"investor.{action}",
        target_type="investor_profile",
        target_id=profile.id,
        metadata={"from": previous.value, "to": user.status.value, "reason": reason},
    )

    template = {
        "approve": "status_approved",
        "reject": "status_rejected",
        "request_info": "status_request_info",
    }.get(action)
    if template and user.email:
        # Queued (ARQ) so the admin action never waits on the email provider.
        await enqueue(
            "send_templated_email",
            to=user.email,
            template=template,
            locale=user.locale.value,
            reason=reason or "",
        )
    await notification_service.create(
        db,
        user_id=user.id,
        type="status_change",
        title=f"Your account status is now {user.status.value}",
        body=reason,
    )
    # Generate matches once an investor is approved (PRD §12.3).
    if action == "approve":
        await enqueue("generate_matches", str(profile.id))
    return profile


async def list_investors(
    db: AsyncSession, *, status: UserStatus | None, page: Pagination
) -> list[InvestorProfile]:
    stmt: Select = (
        select(InvestorProfile)
        .join(User, User.id == InvestorProfile.user_id)
        .order_by(InvestorProfile.created_at.desc(), InvestorProfile.id.desc())
        .limit(page.limit + 1)
    )
    if status is not None:
        stmt = stmt.where(User.status == status)
    if page.cursor is not None:
        stmt = stmt.where(InvestorProfile.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ─────────────────────── Project administration ───────────────────────
async def set_project_status(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    action: str,
    reason: str | None,
    risk_level: str | None,
    actor_id: uuid.UUID,
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    previous = project.status

    if action == "approve":
        if not risk_level:
            raise ValidationError("risk_level is required when approving a project.")
        try:
            project.risk_level = RiskLevel(risk_level)
        except ValueError as exc:
            raise ValidationError(f"Invalid risk_level: {risk_level}") from exc
        project.status = ProjectStatus.approved
    elif action == "reject":
        project.status = ProjectStatus.rejected
    elif action == "suspend":
        project.status = ProjectStatus.suspended
    elif action == "feature":
        project.is_featured = not project.is_featured
    else:
        raise ValidationError(f"Unknown action: {action}")
    await db.flush()

    await audit_service.record(
        db,
        actor_user_id=actor_id,
        action=f"project.{action}",
        target_type="project",
        target_id=project.id,
        metadata={
            "from": previous.value,
            "to": project.status.value,
            "reason": reason,
            "risk_level": risk_level,
        },
    )
    owner = await db.get(User, project.owner_user_id)
    if owner and owner.email and action in {"approve", "reject"}:
        await enqueue(
            "send_templated_email",
            to=owner.email,
            template="project_status",
            locale=owner.locale.value,
            title=project.title,
            status=project.status.value,
            reason=reason or "",
        )
    if action == "approve" and previous != ProjectStatus.approved:
        # Re-run matching against the new approved project, suggest a risk
        # assessment to admins (advisory only — PRD §12.5), and alert
        # investors whose focus overlaps the new listing (PRD §6.5).
        await enqueue("embed_project", str(project.id))
        await enqueue("assess_project_risk", str(project.id))
        await enqueue("notify_matching_investors", str(project.id))
    return project


async def list_projects(
    db: AsyncSession, *, status: ProjectStatus | None, page: Pagination
) -> list[Project]:
    stmt = select(Project).order_by(Project.created_at.desc(), Project.id.desc()).limit(
        page.limit + 1
    )
    if status is not None:
        stmt = stmt.where(Project.status == status)
    if page.cursor is not None:
        stmt = stmt.where(Project.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ─────────────────────── Consultant administration ───────────────────────
async def set_consultant_status(
    db: AsyncSession, *, consultant_id: uuid.UUID, action: str, actor_id: uuid.UUID
) -> ConsultantProfile:
    profile = await db.get(ConsultantProfile, consultant_id)
    if profile is None:
        raise NotFoundError("Consultant not found.")

    if action == "approve":
        profile.status = ConsultantStatus.approved
    elif action == "suspend":
        profile.status = ConsultantStatus.suspended
    elif action == "reject":
        profile.status = ConsultantStatus.suspended
    elif action == "verify":
        profile.is_verified = not profile.is_verified
    else:
        raise ValidationError(f"Unknown action: {action}")
    await db.flush()

    await audit_service.record(
        db,
        actor_user_id=actor_id,
        action=f"consultant.{action}",
        target_type="consultant_profile",
        target_id=profile.id,
        metadata={"status": profile.status.value, "is_verified": profile.is_verified},
    )
    return profile


async def list_consultants(
    db: AsyncSession, *, status: ConsultantStatus | None, page: Pagination
) -> list[ConsultantProfile]:
    stmt = select(ConsultantProfile).order_by(
        ConsultantProfile.created_at.desc(), ConsultantProfile.id.desc()
    ).limit(page.limit + 1)
    if status is not None:
        stmt = stmt.where(ConsultantProfile.status == status)
    if page.cursor is not None:
        stmt = stmt.where(ConsultantProfile.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ─────────────────────────── CSV export ───────────────────────────
async def export_investors_csv(db: AsyncSession) -> str:
    result = await db.execute(
        select(InvestorProfile, User).join(User, User.id == InvestorProfile.user_id)
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "company_name", "country", "contact_email", "status", "created_at"]
    )
    for profile, user in result.all():
        writer.writerow(
            [
                str(profile.id),
                profile.company_name,
                profile.country_of_registration,
                profile.contact_email or user.email or "",
                user.status.value,
                profile.created_at.isoformat(),
            ]
        )
    return buffer.getvalue()


async def export_projects_csv(db: AsyncSession) -> str:
    result = await db.execute(select(Project))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "title", "sector", "country", "funding_required", "status", "risk_level"]
    )
    for p in result.scalars().all():
        writer.writerow(
            [
                str(p.id),
                p.title,
                p.sector,
                p.country,
                str(p.funding_required),
                p.status.value,
                p.risk_level.value if p.risk_level else "",
            ]
        )
    return buffer.getvalue()


# ─────────────────────────── User administration ───────────────────────────
async def list_users(db: AsyncSession, *, page: Pagination) -> list[User]:
    stmt = select(User).order_by(User.created_at.desc(), User.id.desc()).limit(page.limit + 1)
    if page.cursor is not None:
        stmt = stmt.where(User.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_by(
    db: AsyncSession, model: type, column: object, *, where: object | None = None
) -> dict[str, int]:
    """Simple group-by count helper for the analytics overview. ``where``
    narrows the population (e.g. only users with the investor role)."""
    import enum

    stmt = select(column, func.count()).group_by(column)
    if where is not None:
        stmt = stmt.where(where)
    result = await db.execute(stmt)
    return {(k.value if isinstance(k, enum.Enum) else str(k)): v for k, v in result.all()}
