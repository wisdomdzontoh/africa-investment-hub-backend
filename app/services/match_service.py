"""Match service — pipeline management and manual matches (PRD §6.4, §12.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import MatchSource, MatchStatus
from app.models.investor import InvestorProfile
from app.models.match import Match
from app.models.project import Project
from app.models.user import User
from app.services import notification_service


async def get_or_404(db: AsyncSession, match_id: uuid.UUID) -> Match:
    match = await db.get(Match, match_id)
    if match is None:
        raise NotFoundError("Match not found.")
    return match


# Investor-driven transitions (PRD §6.7, §12.3). An investor may act on a match
# only while it is visible to them and before the deal moves into the brokered
# NDA stages — past that, the admin/legal flow owns the status.
_INTEREST_ALLOWED_FROM = frozenset(
    {MatchStatus.admin_reviewed, MatchStatus.investor_notified}
)
_DISMISS_ALLOWED_FROM = frozenset(
    {
        MatchStatus.admin_reviewed,
        MatchStatus.investor_notified,
        MatchStatus.investor_interested,
    }
)
_CONFIDENTIAL_ALLOWED_FROM = _DISMISS_ALLOWED_FROM


async def get_owned_or_403(
    db: AsyncSession, *, match_id: uuid.UUID, investor_id: uuid.UUID
) -> Match:
    """Fetch a match, 404 if missing, 403 if it isn't this investor's."""
    from app.core.exceptions import ForbiddenError

    match = await get_or_404(db, match_id)
    if match.investor_id != investor_id:
        raise ForbiddenError("This match does not belong to you.")
    return match


async def express_interest(db: AsyncSession, *, match: Match) -> Match:
    if match.status not in _INTEREST_ALLOWED_FROM:
        raise ConflictError("Interest can't be registered for this match right now.")
    match.status = MatchStatus.investor_interested
    if match.investor_interest_at is None:
        match.investor_interest_at = datetime.now(UTC)
    await db.flush()
    return match


# Statuses from which browsing-driven interest may (re)start. ``dismissed`` is
# included deliberately: an investor who dismissed a suggestion can change
# their mind from the catalogue.
_BROWSE_INTEREST_ALLOWED_FROM = frozenset(
    {
        MatchStatus.ai_recommended,
        MatchStatus.admin_reviewed,
        MatchStatus.investor_notified,
        MatchStatus.dismissed,
    }
)


async def express_interest_in_project(
    db: AsyncSession,
    *,
    investor: InvestorProfile,
    investor_user: User,
    project_id: uuid.UUID,
) -> Match:
    """Investor-initiated interest straight from the catalogue (no prior match
    needed). Creates or advances the match to ``investor_interested`` and
    notifies the project facilitator and every admin. Idempotent: a match
    already at or past interest is returned unchanged.

    Human review still owns everything after this point (PRD §6.7): interest
    only signals intent — admins move the pipeline forward.
    """
    from app.models.enums import ProjectStatus, UserRole
    from app.workers.queue import enqueue

    project = await db.get(Project, project_id)
    if project is None or project.status != ProjectStatus.approved:
        raise NotFoundError("Project not found.")

    existing = (
        await db.execute(
            select(Match).where(
                Match.investor_id == investor.id, Match.project_id == project_id
            )
        )
    ).scalar_one_or_none()

    if existing is not None and existing.status not in _BROWSE_INTEREST_ALLOWED_FROM:
        return existing  # already interested or further along — nothing to do

    if existing is not None:
        match = existing
        match.status = MatchStatus.investor_interested
        if match.investor_interest_at is None:
            match.investor_interest_at = datetime.now(UTC)
    else:
        match = Match(
            investor_id=investor.id,
            project_id=project_id,
            source=MatchSource.investor_initiated,
            status=MatchStatus.investor_interested,
            investor_interest_at=datetime.now(UTC),
        )
        db.add(match)
    await db.flush()

    # Notify the facilitator (in-app + email) and every admin (in-app).
    # Confidential engagements never leak the investor's identity (PRD §6.9).
    company = (
        "An investor"
        if match.is_confidential
        else (investor.company_name or "An investor")
    )
    owner = await db.get(User, project.owner_user_id)
    if owner is not None:
        await notification_service.create(
            db,
            user_id=owner.id,
            type="project_interest",
            title=f"An investor is interested in {project.title}",
            body=f"{company} has expressed interest. Our team will coordinate next steps.",
            link="/facilitator/interest",
        )
        if owner.email:
            await enqueue(
                "send_templated_email",
                to=owner.email,
                template="project_interest",
                locale=owner.locale.value,
                title=project.title,
            )
    admins = (
        await db.execute(
            select(User).where(User.role == UserRole.admin, User.deleted_at.is_(None))
        )
    ).scalars()
    for admin in admins:
        await notification_service.create(
            db,
            user_id=admin.id,
            type="project_interest",
            title=f"Investor interest: {project.title}",
            body=f"{company} expressed interest — review the match pipeline.",
            link="/admin/matches",
        )

    from app.services import audit_service

    await audit_service.record(
        db,
        actor_user_id=investor_user.id,
        action="match.investor_interest",
        target_type="match",
        target_id=match.id,
        metadata={"project_id": str(project_id), "source": match.source.value},
    )
    return match


async def dismiss(db: AsyncSession, *, match: Match) -> Match:
    if match.status not in _DISMISS_ALLOWED_FROM:
        raise ConflictError("This match can no longer be dismissed.")
    match.status = MatchStatus.dismissed
    await db.flush()
    return match


async def set_confidential(db: AsyncSession, *, match: Match, value: bool) -> Match:
    if match.status not in _CONFIDENTIAL_ALLOWED_FROM:
        raise ConflictError("Confidential mode can't be changed at this stage.")
    match.is_confidential = value
    await db.flush()
    return match


async def sign_nda(db: AsyncSession, *, match: Match) -> Match:
    """Investor signs the NDA an admin has sent (PRD §6.10). Unlocks the deal
    room's privileged content by advancing to ``nda_signed``."""
    if match.status != MatchStatus.nda_sent:
        raise ConflictError("There's no NDA awaiting your signature on this match.")
    match.status = MatchStatus.nda_signed
    await db.flush()
    return match


# ─────────────────────────── Deal room (PRD §6.10) ───────────────────────────
async def get_accessible_match(
    db: AsyncSession, *, match_id: uuid.UUID, user: User
) -> Match:
    """Fetch a match the caller may open in the deal room: the matched investor,
    the project's facilitator, or an admin."""
    from app.models.enums import UserRole

    match = await get_or_404(db, match_id)
    if user.role == UserRole.admin:
        return match

    # Matched investor?
    investor = await db.execute(
        select(InvestorProfile.id).where(InvestorProfile.user_id == user.id)
    )
    investor_id = investor.scalar_one_or_none()
    if investor_id is not None and match.investor_id == investor_id:
        return match

    # Project facilitator (owner)?
    project = await db.get(Project, match.project_id)
    if project is not None and project.owner_user_id == user.id:
        return match

    from app.core.exceptions import ForbiddenError

    raise ForbiddenError("You don't have access to this deal room.")


async def deal_room_view(
    db: AsyncSession, *, match: Match, user: User
) -> tuple[Project, bool]:
    """Return the match's project and whether NDA-gated content is unlocked for
    this caller (admin/owner always; investor only at ``nda_signed`` or beyond)."""
    from app.models.enums import NDA_UNLOCKED_STATUSES, UserRole

    project = await db.get(Project, match.project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    privileged = (
        user.role == UserRole.admin
        or project.owner_user_id == user.id
        or match.status in NDA_UNLOCKED_STATUSES
    )
    return project, privileged


async def create_manual(
    db: AsyncSession, *, investor_id: uuid.UUID, project_id: uuid.UUID, explanation: str | None
) -> Match:
    """Admin creates a match directly (PRD §6.4 Match Management)."""
    if await db.get(InvestorProfile, investor_id) is None:
        raise NotFoundError("Investor not found.")
    if await db.get(Project, project_id) is None:
        raise NotFoundError("Project not found.")

    existing = await db.execute(
        select(Match).where(Match.investor_id == investor_id, Match.project_id == project_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("A match already exists for this investor and project.")

    match = Match(
        investor_id=investor_id,
        project_id=project_id,
        explanation=explanation,
        source=MatchSource.admin_manual,
        status=MatchStatus.admin_reviewed,
        admin_reviewed_at=datetime.now(UTC),
    )
    db.add(match)
    await db.flush()
    return match


# Stages a facilitator may see: from the investor's raised hand onward.
# AI suggestions and admin triage stay internal until an investor acts.
_FACILITATOR_VISIBLE_STATUSES = frozenset(
    {
        MatchStatus.investor_interested,
        MatchStatus.nda_sent,
        MatchStatus.nda_signed,
        MatchStatus.confidential,
        MatchStatus.mou_drafted,
        MatchStatus.mou_signed,
        MatchStatus.in_negotiation,
        MatchStatus.due_diligence,
        MatchStatus.closed_won,
        MatchStatus.closed_lost,
    }
)


async def list_for_facilitator(
    db: AsyncSession, *, owner_id: uuid.UUID, page: Pagination
) -> list[tuple[Match, Project, InvestorProfile]]:
    """Matches on the facilitator's own projects, newest first — only stages
    where an investor has actually engaged (PRD §6.9)."""
    stmt = (
        select(Match, Project, InvestorProfile)
        .join(Project, Project.id == Match.project_id)
        .join(InvestorProfile, InvestorProfile.id == Match.investor_id)
        .where(
            Project.owner_user_id == owner_id,
            Match.status.in_(_FACILITATOR_VISIBLE_STATUSES),
        )
        .order_by(Match.created_at.desc(), Match.id.desc())
        .limit(page.limit + 1)
    )
    if page.cursor is not None:
        stmt = stmt.where(Match.id != page.cursor)
    result = await db.execute(stmt)
    return [(m, p, i) for m, p, i in result.all()]


def _admin_list_stmt(status: MatchStatus | None) -> Select[tuple[Match]]:
    stmt = select(Match).order_by(Match.created_at.desc(), Match.id.desc())
    if status is not None:
        stmt = stmt.where(Match.status == status)
    return stmt


async def list_all(
    db: AsyncSession, *, status: MatchStatus | None, page: Pagination
) -> list[Match]:
    stmt = _admin_list_stmt(status).limit(page.limit + 1)
    if page.cursor is not None:
        stmt = stmt.where(Match.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_status(
    db: AsyncSession, *, match: Match, status: MatchStatus
) -> Match:
    """Move a match through the pipeline and notify the investor when it
    becomes visible to them."""
    previous = match.status
    match.status = status
    if status == MatchStatus.admin_reviewed and match.admin_reviewed_at is None:
        match.admin_reviewed_at = datetime.now(UTC)
    if status == MatchStatus.investor_interested and match.investor_interest_at is None:
        match.investor_interest_at = datetime.now(UTC)
    await db.flush()

    # Notify investor when the match first becomes visible to them.
    if status == MatchStatus.investor_notified and previous != MatchStatus.investor_notified:
        investor = await db.get(InvestorProfile, match.investor_id)
        if investor is not None:
            await notification_service.create(
                db,
                user_id=investor.user_id,
                type="new_match",
                title="A new investment match is available",
                body="Our team has reviewed a project that fits your profile.",
                link=f"/dashboard/matches/{match.id}",
            )
    return match
