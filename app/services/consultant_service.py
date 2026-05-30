"""Consultant/partner service (PRD §6.11)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.exceptions import ConflictError, NotFoundError
from app.models.consultant import ConsultantProfile
from app.models.enums import ConsultantStatus
from app.models.user import User
from app.schemas.consultant import ConsultantRegister, ConsultantUpdate
from app.workers.queue import enqueue


async def get_by_user(db: AsyncSession, user_id: uuid.UUID) -> ConsultantProfile | None:
    result = await db.execute(
        select(ConsultantProfile).where(ConsultantProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_404(db: AsyncSession, consultant_id: uuid.UUID) -> ConsultantProfile:
    profile = await db.get(ConsultantProfile, consultant_id)
    if profile is None:
        raise NotFoundError("Consultant profile not found.")
    return profile


async def register(
    db: AsyncSession, *, user: User, payload: ConsultantRegister
) -> ConsultantProfile:
    if await get_by_user(db, user.id) is not None:
        raise ConflictError("A consultant profile already exists for this account.")
    profile = ConsultantProfile(
        user_id=user.id, status=ConsultantStatus.pending, **payload.model_dump()
    )
    db.add(profile)
    await db.flush()
    await enqueue("embed_consultant", str(profile.id))
    return profile


async def update(
    db: AsyncSession, *, profile: ConsultantProfile, payload: ConsultantUpdate
) -> ConsultantProfile:
    changed = payload.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(profile, field, value)
    await db.flush()
    if changed.keys() & {"expertise_areas", "sectors_served", "bio", "key_achievements"}:
        await enqueue("embed_consultant", str(profile.id))
    return profile


def _apply_search(stmt: Select[Any], *, expertise: str | None, country: str | None, sector: str | None) -> Select[Any]:
    if expertise:
        stmt = stmt.where(ConsultantProfile.expertise_areas.any(expertise))
    if country:
        stmt = stmt.where(ConsultantProfile.country == country)
    if sector:
        stmt = stmt.where(ConsultantProfile.sectors_served.any(sector))
    return stmt


async def search_approved(
    db: AsyncSession,
    *,
    expertise: str | None,
    country: str | None,
    sector: str | None,
    page: Pagination,
) -> list[ConsultantProfile]:
    """Investor-only consultant discovery (PRD §6.11 — approved only)."""
    stmt = select(ConsultantProfile).where(ConsultantProfile.status == ConsultantStatus.approved)
    stmt = _apply_search(stmt, expertise=expertise, country=country, sector=sector)
    stmt = stmt.order_by(
        ConsultantProfile.is_verified.desc(), ConsultantProfile.created_at.desc()
    ).limit(page.limit + 1)
    if page.cursor is not None:
        stmt = stmt.where(ConsultantProfile.id != page.cursor)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_approved_or_404(db: AsyncSession, consultant_id: uuid.UUID) -> ConsultantProfile:
    profile = await get_or_404(db, consultant_id)
    if profile.status != ConsultantStatus.approved:
        raise NotFoundError("Consultant profile not found.")
    return profile


async def add_document(
    db: AsyncSession, *, profile: ConsultantProfile, doc: dict[str, Any]
) -> ConsultantProfile:
    doc.setdefault("uploaded_at", datetime.now(UTC).isoformat())
    profile.documents = [*profile.documents, doc]
    await db.flush()
    return profile
