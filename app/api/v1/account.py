"""Account endpoints — GDPR data deletion (PRD §14)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbDep
from app.core.clerk_client import delete_user as clerk_delete_user
from app.core.clerk_client import update_user_public_metadata
from app.core.exceptions import ConflictError, ForbiddenError, ValidationError
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.user import AccountRoleSet, LocaleUpdate, UserOut
from app.services import audit_service, user_service

router = APIRouter(tags=["account"])


async def _user_with_profiles(db: DbDep, user_id) -> User | None:
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.investor_profile),
            selectinload(User.consultant_profile),
            selectinload(User.projects),
        )
    )
    return result.scalar_one_or_none()


@router.get("/account", response_model=UserOut)
async def get_account(db: DbDep, user: CurrentUser) -> UserOut:
    loaded = await _user_with_profiles(db, user.id) or user
    out = UserOut.model_validate(loaded)
    out.onboarding_complete = bool(loaded.investor_profile or loaded.projects)
    return out


@router.post("/account/role", response_model=UserOut)
async def set_account_role(payload: AccountRoleSet, db: DbDep, user: CurrentUser) -> UserOut:
    """Choose platform role during onboarding (once, before profile submission)."""
    if payload.role not in (UserRole.investor, UserRole.project_owner):
        raise ValidationError("Role must be investor or project_owner.")
    if user.role == UserRole.admin:
        raise ForbiddenError("Admin role cannot be changed via onboarding.")

    loaded = await _user_with_profiles(db, user.id)
    if loaded is None:
        raise ForbiddenError("User not found.")
    if loaded.investor_profile or loaded.consultant_profile or loaded.projects:
        raise ConflictError("Account role has already been set.")

    user.role = payload.role
    await db.flush()
    await update_user_public_metadata(user.clerk_id, {"role": payload.role.value})
    await audit_service.record(
        db,
        actor_user_id=user.id,
        action="account.role_selected",
        target_type="user",
        target_id=user.id,
        metadata={"role": payload.role.value},
    )
    return UserOut.model_validate(user)


@router.patch("/account/locale", response_model=UserOut)
async def set_locale(payload: LocaleUpdate, db: DbDep, user: CurrentUser) -> UserOut:
    user.locale = payload.locale
    await db.flush()
    return UserOut.model_validate(user)


@router.delete("/account", response_model=MessageResponse)
async def delete_account(db: DbDep, user: CurrentUser) -> MessageResponse:
    """Soft-delete now; a scheduled task hard-deletes after 30 days (PRD §14).

    The Clerk identity is deleted immediately so the account can no longer
    sign in anywhere. If the Clerk call fails transiently, the nightly
    reconciliation job re-drives it from ``deleted_at``."""
    await user_service.soft_delete(db, user)
    clerk_deleted = await clerk_delete_user(user.clerk_id)
    await audit_service.record(
        db,
        actor_user_id=user.id,
        action="account.deletion_requested",
        target_type="user",
        target_id=user.id,
        metadata={"clerk_deleted": clerk_deleted},
    )
    return MessageResponse(
        message="Your account has been deactivated and will be permanently deleted in 30 days."
    )
