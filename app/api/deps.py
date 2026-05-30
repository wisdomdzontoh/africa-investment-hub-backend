"""Shared FastAPI dependencies: authentication, role guards, pagination, locale.

Security is enforced server-side only (PRD §14). ``get_current_user`` verifies
the Clerk JWT and resolves (auto-provisioning on first sight) the application
user. Role and ownership checks build on top.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import verify_token
from app.db.session import get_db
from app.models.enums import Locale, UserRole, UserStatus
from app.models.user import User
from app.services import user_service


def _ensure_active_user(user: User) -> User:
    if user.deleted_at is not None or user.status == UserStatus.suspended:
        raise UnauthorizedError("This account has been deactivated.")
    return user

# auto_error=False so we can raise our unified error shape instead of FastAPI's.
_bearer = HTTPBearer(auto_error=False)

DbDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing authentication credentials.")
    claims = await verify_token(credentials.credentials)
    user = await user_service.get_or_provision(db, claims)
    return _ensure_active_user(user)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    db: DbDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    """Resolve the user if a valid token is present; otherwise ``None``.

    Used by public endpoints whose response is enriched for logged-in users
    (e.g. project detail gating).
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        claims = await verify_token(credentials.credentials)
    except UnauthorizedError:
        return None
    return await user_service.get_or_provision(db, claims)


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_role(
    *roles: UserRole,
) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Dependency factory enforcing that the caller holds one of ``roles``."""

    async def _checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise ForbiddenError("You do not have access to this resource.")
        return user

    return _checker


async def require_approved(user: CurrentUser) -> User:
    """Caller must be an approved account (PRD §6.2 — gated platform access)."""
    if user.status != UserStatus.approved:
        raise ForbiddenError("Your account is not yet approved.")
    return user


# Convenience role dependencies.
require_admin = require_role(UserRole.admin)
require_investor = require_role(UserRole.investor)
require_project_owner = require_role(UserRole.project_owner)

AdminUser = Annotated[User, Depends(require_admin)]
ApprovedUser = Annotated[User, Depends(require_approved)]


@dataclass(slots=True)
class Pagination:
    """Cursor-based pagination params (PRD §11)."""

    cursor: uuid.UUID | None
    limit: int


def get_pagination(
    cursor: Annotated[uuid.UUID | None, Query(description="Last id from previous page")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Pagination:
    return Pagination(cursor=cursor, limit=limit)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]


def get_locale(
    request: Request,
    accept_language: Annotated[str | None, Header()] = None,
) -> Locale:
    """Resolve locale, preferring the value set by ``LocaleMiddleware``."""
    from app.core.i18n import get_request_locale, parse_accept_language

    locale = get_request_locale(request)
    if locale is Locale.en and accept_language:
        return parse_accept_language(accept_language)
    return locale


LocaleDep = Annotated[Locale, Depends(get_locale)]
