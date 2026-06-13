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
