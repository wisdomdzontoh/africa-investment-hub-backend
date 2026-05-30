"""User service — provisioning and lookup tied to Clerk identities."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ClerkClaims
from app.models.enums import UserRole, UserStatus
from app.models.user import User


async def get_by_clerk_id(db: AsyncSession, clerk_id: str) -> User | None:
    result = await db.execute(select(User).where(User.clerk_id == clerk_id))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_or_provision(db: AsyncSession, claims: ClerkClaims) -> User:
    """Return the app user for a verified token, creating it on first sight.

    The role in the token (Clerk ``publicMetadata``) is authoritative and kept
    in sync on every request. New users start ``pending`` until an admin
    approves them (PRD §6.2).
    """
    user = await get_by_clerk_id(db, claims.clerk_id)
    if user is None:
        user = User(
            clerk_id=claims.clerk_id,
            email=claims.email,
            role=claims.role or UserRole.investor,
            status=UserStatus.pending,
        )
        db.add(user)
        await db.flush()
        return user

    # Keep email/role aligned with Clerk as the source of truth.
    changed = False
    if claims.email and user.email != claims.email:
        user.email = claims.email
        changed = True
    if claims.role and user.role != claims.role:
        user.role = claims.role
        changed = True
    if changed:
        await db.flush()
    return user


async def upsert_from_webhook(
    db: AsyncSession,
    *,
    clerk_id: str,
    email: str | None,
    role: UserRole | None,
) -> User:
    """Create or update a user from a Clerk webhook (user.created/updated)."""
    user = await get_by_clerk_id(db, clerk_id)
    if user is None:
        user = User(
            clerk_id=clerk_id,
            email=email,
            role=role or UserRole.investor,
            status=UserStatus.pending,
        )
        db.add(user)
    else:
        if email is not None:
            user.email = email
        if role is not None:
            user.role = role
    await db.flush()
    return user


async def soft_delete_by_clerk_id(db: AsyncSession, clerk_id: str) -> None:
    """Mark a user deleted in response to a Clerk ``user.deleted`` webhook."""
    from datetime import UTC, datetime

    user = await get_by_clerk_id(db, clerk_id)
    if user is not None:
        user.status = UserStatus.suspended
        user.deleted_at = datetime.now(UTC)
        await db.flush()
