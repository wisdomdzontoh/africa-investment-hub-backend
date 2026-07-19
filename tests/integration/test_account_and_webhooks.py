"""GDPR account deletion + Clerk webhook sync (PRD §8.5, §14)."""

from __future__ import annotations

import json

import pytest
from app.models.enums import UserRole, UserStatus

pytestmark = pytest.mark.integration


async def test_get_account(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    resp = await client.get("/v1/account")
    assert resp.status_code == 200
    assert resp.json()["role"] == "investor"


async def test_delete_account_soft_deletes(client, db, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    resp = await client.delete("/v1/account")
    assert resp.status_code == 200

    await db.refresh(user)
    assert user.status == UserStatus.suspended
    assert user.deleted_at is not None


async def test_delete_account_deletes_clerk_identity(
    client, make_user, auth_as, monkeypatch
) -> None:
    deleted: list[str] = []

    async def _mock_delete(clerk_id: str) -> bool:
        deleted.append(clerk_id)
        return True

    monkeypatch.setattr("app.api.v1.account.clerk_delete_user", _mock_delete)

    user = await make_user(role=UserRole.investor)
    auth_as(user)
    resp = await client.delete("/v1/account")
    assert resp.status_code == 200
    assert deleted == [user.clerk_id]


async def test_set_locale(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    resp = await client.patch("/v1/account/locale", json={"locale": "fr"})
    assert resp.status_code == 200
    assert resp.json()["locale"] == "fr"


async def test_suspended_user_cannot_access_account(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor, status=UserStatus.suspended)
    auth_as(user)
    resp = await client.get("/v1/account")
    assert resp.status_code == 401


async def test_optional_user_treats_suspended_as_anonymous(db, make_user, monkeypatch) -> None:
    """A deactivated account's still-valid token must never enrich responses."""
    from app.api import deps
    from app.core.security import ClerkClaims
    from fastapi.security import HTTPAuthorizationCredentials

    suspended = await make_user(role=UserRole.investor, status=UserStatus.suspended)
    approved = await make_user(role=UserRole.investor, status=UserStatus.approved)
    current = {"clerk_id": suspended.clerk_id}

    async def _mock_verify(token: str) -> ClerkClaims:
        return ClerkClaims(clerk_id=current["clerk_id"], email=None, role=None, raw={})

    monkeypatch.setattr(deps, "verify_token", _mock_verify)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")

    assert await deps.get_optional_user(db, creds) is None

    current["clerk_id"] = approved.clerk_id
    resolved = await deps.get_optional_user(db, creds)
    assert resolved is not None and resolved.id == approved.id


async def test_set_account_role(client, make_user, auth_as, monkeypatch) -> None:
    calls: list[dict] = []

    async def _mock_sync(clerk_id: str, public_metadata: dict) -> None:
        calls.append({"clerk_id": clerk_id, "public_metadata": public_metadata})

    monkeypatch.setattr("app.api.v1.account.update_user_public_metadata", _mock_sync)

    user = await make_user(role=UserRole.investor, status=UserStatus.pending)
    auth_as(user)
    resp = await client.post("/v1/account/role", json={"role": "project_owner"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "project_owner"
    assert calls == [{"clerk_id": user.clerk_id, "public_metadata": {"role": "project_owner"}}]


async def test_set_account_role_rejected_after_profile(client, db, make_user, auth_as) -> None:
    from app.models.investor import InvestorProfile

    user = await make_user(role=UserRole.investor, status=UserStatus.pending)
    db.add(InvestorProfile(user_id=user.id, company_name="Acme", country_of_registration="US"))
    await db.commit()
    auth_as(user)
    resp = await client.post("/v1/account/role", json={"role": "project_owner"})
    assert resp.status_code == 409


# ─────────────────── Admin-side sync (DB → Clerk) ───────────────────
async def test_admin_delete_user_propagates_to_clerk(
    client, db, make_user, auth_as, monkeypatch
) -> None:
    deleted: list[str] = []

    async def _mock_delete(clerk_id: str) -> bool:
        deleted.append(clerk_id)
        return True

    monkeypatch.setattr("app.core.clerk_client.delete_user", _mock_delete)

    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.investor)
    auth_as(admin)

    resp = await client.delete(f"/v1/admin/users/{target.id}")
    assert resp.status_code == 200
    assert deleted == [target.clerk_id]

    await db.refresh(target)
    assert target.status == UserStatus.suspended
    assert target.deleted_at is not None


async def test_admin_cannot_delete_self(client, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    resp = await client.delete(f"/v1/admin/users/{admin.id}")
    assert resp.status_code == 403


async def test_admin_suspend_bans_in_clerk(
    client, db, make_user, auth_as, monkeypatch
) -> None:
    banned: list[str] = []
    unbanned: list[str] = []

    async def _mock_ban(clerk_id: str) -> bool:
        banned.append(clerk_id)
        return True

    async def _mock_unban(clerk_id: str) -> bool:
        unbanned.append(clerk_id)
        return True

    monkeypatch.setattr("app.core.clerk_client.ban_user", _mock_ban)
    monkeypatch.setattr("app.core.clerk_client.unban_user", _mock_unban)

    admin = await make_user(role=UserRole.admin)
    target = await make_user(role=UserRole.investor)
    auth_as(admin)

    resp = await client.patch(
        f"/v1/admin/users/{target.id}/status", json={"status": "suspended"}
    )
    assert resp.status_code == 200
    assert banned == [target.clerk_id]

    resp = await client.patch(
        f"/v1/admin/users/{target.id}/status", json={"status": "approved"}
    )
    assert resp.status_code == 200
    assert unbanned == [target.clerk_id]


async def test_admin_cannot_change_own_status(client, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    resp = await client.patch(
        f"/v1/admin/users/{admin.id}/status", json={"status": "suspended"}
    )
    assert resp.status_code == 403


# ─────────────────── Scheduled sync jobs (cron tasks) ───────────────────
async def test_purge_deleted_users_task(db, make_user, monkeypatch) -> None:
    import datetime

    from app.models.investor import InvestorProfile
    from app.services import user_service
    from app.workers import tasks
    from sqlalchemy.ext.asyncio import async_sessionmaker

    clerk_deleted: list[str] = []

    async def _mock_delete(clerk_id: str) -> bool:
        clerk_deleted.append(clerk_id)
        return True

    monkeypatch.setattr("app.core.clerk_client.delete_user", _mock_delete)
    monkeypatch.setattr(
        tasks, "SessionLocal", async_sessionmaker(bind=db.bind, expire_on_commit=False)
    )

    expired = await make_user(role=UserRole.investor, status=UserStatus.suspended)
    expired.deleted_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=31)
    recent = await make_user(role=UserRole.investor, status=UserStatus.suspended)
    recent.deleted_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=5)
    db.add(
        InvestorProfile(
            user_id=expired.id,
            company_name="Acme",
            country_of_registration="US",
            documents=[{"type": "aml_certificate", "r2_key": "docs/a.pdf", "filename": "a.pdf"}],
        )
    )
    await db.commit()

    purged = await tasks.purge_deleted_users({})
    assert purged == 1
    assert clerk_deleted == [expired.clerk_id]

    # Expired user hard-deleted (profile cascades); recent one retained.
    assert await user_service.get_by_clerk_id(db, expired.clerk_id) is None
    assert await user_service.get_by_clerk_id(db, recent.clerk_id) is not None


async def test_reconcile_clerk_users_task(db, make_user, monkeypatch) -> None:
    from app.services import user_service
    from app.workers import tasks
    from sqlalchemy.ext.asyncio import async_sessionmaker

    clerk_deleted: list[str] = []

    async def _mock_delete(clerk_id: str) -> bool:
        clerk_deleted.append(clerk_id)
        return True

    async def _mock_list_users(*, limit: int = 100, offset: int = 0) -> list[dict]:
        if offset > 0:
            return []
        return [
            {
                "id": "clerk_reconciled_user",
                "email_addresses": [{"id": "e1", "email_address": "missed@test.com"}],
                "primary_email_address_id": "e1",
                "public_metadata": {"role": "investor"},
            }
        ]

    monkeypatch.setattr("app.core.clerk_client.delete_user", _mock_delete)
    monkeypatch.setattr("app.core.clerk_client.list_users", _mock_list_users)
    monkeypatch.setattr(
        tasks, "SessionLocal", async_sessionmaker(bind=db.bind, expire_on_commit=False)
    )

    # A locally deleted user still lingering in Clerk → deletion re-driven.
    ghost = await make_user(role=UserRole.investor, status=UserStatus.suspended)
    await user_service.soft_delete(db, ghost)
    await db.commit()

    result = await tasks.reconcile_clerk_users({})
    assert result["deleted_in_clerk"] == 1
    assert clerk_deleted == [ghost.clerk_id]
    assert result["upserted"] == 1

    # The Clerk user missed by webhooks now exists locally.
    synced = await user_service.get_by_clerk_id(db, "clerk_reconciled_user")
    assert synced is not None
    assert synced.email == "missed@test.com"


async def test_webhook_rejects_bad_signature(client, monkeypatch) -> None:
    # With a configured secret, an unsigned request must be rejected.
    from app.core import config

    monkeypatch.setattr(config.settings, "CLERK_WEBHOOK_SECRET", "whsec_dGVzdHNlY3JldA==")
    resp = await client.post(
        "/v1/webhooks/clerk",
        content=json.dumps({"type": "user.created", "data": {"id": "x"}}),
        headers={"svix-id": "a", "svix-timestamp": "1", "svix-signature": "v1,bad"},
    )
    assert resp.status_code == 401


async def test_webhook_valid_signature_syncs_user(client, db, monkeypatch) -> None:
    import datetime

    from app.core import config
    from app.services import user_service
    from svix.webhooks import Webhook

    # Svix secrets are "whsec_" + base64; sign with a known one.
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    monkeypatch.setattr(config.settings, "CLERK_WEBHOOK_SECRET", secret)

    payload = json.dumps(
        {
            "type": "user.created",
            "data": {
                "id": "clerk_webhook_user",
                "email_addresses": [{"id": "e1", "email_address": "wh@test.com"}],
                "primary_email_address_id": "e1",
                "public_metadata": {"role": "investor"},
            },
        }
    )
    msg_id = "msg_test_1"
    timestamp = datetime.datetime.now(datetime.UTC)
    signature = Webhook(secret).sign(msg_id, timestamp, payload)

    resp = await client.post(
        "/v1/webhooks/clerk",
        content=payload,
        headers={
            "svix-id": msg_id,
            "svix-timestamp": str(int(timestamp.timestamp())),
            "svix-signature": signature,
        },
    )
    assert resp.status_code == 200
    user = await user_service.get_by_clerk_id(db, "clerk_webhook_user")
    assert user is not None
    assert user.email == "wh@test.com"
