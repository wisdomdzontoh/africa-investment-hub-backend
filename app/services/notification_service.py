"""In-app notification service (PRD §6.5, §8.6)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.models.notification import Notification


async def create(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    n = Notification(user_id=user_id, type=type, title=title, body=body, link=link)
    db.add(n)
    await db.flush()
    return n


async def list_for_user(
    db: AsyncSession, user_id: uuid.UUID, page: Pagination
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(page.limit + 1)
    )
    if page.cursor is not None:
        anchor = await db.get(Notification, page.cursor)
        if anchor is not None:
            stmt = stmt.where(Notification.created_at < anchor.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_read(
    db: AsyncSession, *, notification_id: uuid.UUID, user_id: uuid.UUID, is_read: bool
) -> Notification | None:
    n = await db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        return None
    n.is_read = is_read
    await db.flush()
    return n
