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

    from svix.webhooks import Webhook

    from app.core import config
    from app.services import user_service

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
