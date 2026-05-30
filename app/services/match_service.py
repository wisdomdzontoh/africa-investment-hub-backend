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
