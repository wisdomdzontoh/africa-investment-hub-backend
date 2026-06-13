"""Investor profile service (PRD §6.2, §6.5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.exceptions import ConflictError, NotFoundError
from app.models.enums import UserStatus
from app.models.investor import InvestorProfile
from app.models.match import Match
from app.models.user import User
from app.schemas.investor import InvestorRegister, InvestorUpdate
from app.services import email as email_service
from app.workers.queue import enqueue


async def get_by_user(db: AsyncSession, user_id: uuid.UUID) -> InvestorProfile | None:
    result = await db.execute(
        select(InvestorProfile).where(InvestorProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_404(db: AsyncSession, investor_id: uuid.UUID) -> InvestorProfile:
    profile = await db.get(InvestorProfile, investor_id)
    if profile is None:
        raise NotFoundError("Investor profile not found.")
    return profile


def _serialise_previous_projects(payload: InvestorRegister) -> list[dict[str, Any]]:
    return [p.model_dump() for p in payload.previous_projects]


async def register(
    db: AsyncSession, *, user: User, payload: InvestorRegister
) -> InvestorProfile:
    """Create the investor profile from the intake form (PRD §6.2).

    Submission leaves the account ``pending`` for admin review and enqueues an
    embedding job so matches can be generated once approved.
    """
    if await get_by_user(db, user.id) is not None:
        raise ConflictError("An investor profile already exists for this account.")

    data = payload.model_dump(exclude={"previous_projects"})
    profile = InvestorProfile(
        user_id=user.id,
        previous_projects=_serialise_previous_projects(payload),
        **data,
    )
    db.add(profile)
    # Ensure the account is in the review queue.
    user.status = UserStatus.pending
    await db.flush()

    await enqueue("embed_profile", str(profile.id))
    if user.email:
        await email_service.send_template(
            to=user.email, template="registration_received", locale=user.locale
        )
    return profile


async def update(
    db: AsyncSession, *, profile: InvestorProfile, payload: InvestorUpdate
) -> InvestorProfile:
    """Update preferences. Triggers re-embedding + re-match (PRD §6.5)."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.flush()

    await enqueue("embed_profile", str(profile.id))
    await enqueue("generate_matches", str(profile.id))
    return profile


async def list_matches(
    db: AsyncSession, *, investor_id: uuid.UUID, page: Pagination
) -> list[Match]:
    """Matches an investor can see — admin-reviewed and beyond (PRD §12.3).

    AI-only matches (``ai_recommended``) are hidden until an admin reviews them.
    """
    from sqlalchemy.orm import selectinload

    from app.models.enums import MatchStatus

    hidden = {MatchStatus.ai_recommended, MatchStatus.dismissed}
    stmt = (
        select(Match)
        .where(Match.investor_id == investor_id, Match.status.not_in(hidden))
        # Eager-load the project so MatchWithProject serialises without a
        # lazy load outside the async context.
        .options(selectinload(Match.project))
        .order_by(Match.score.desc().nullslast(), Match.id.desc())
        .limit(page.limit + 1)
    )
    if page.cursor is not None:
        stmt = stmt.where(Match.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def add_document(
    db: AsyncSession, *, profile: InvestorProfile, doc: dict[str, Any]
) -> InvestorProfile:
    doc.setdefault("uploaded_at", datetime.now(UTC).isoformat())
    profile.documents = [*profile.documents, doc]
    await db.flush()
    return profile


async def remove_document(
    db: AsyncSession, *, profile: InvestorProfile, r2_key: str
) -> InvestorProfile:
    profile.documents = [d for d in profile.documents if d.get("r2_key") != r2_key]
    await db.flush()
    return profile
