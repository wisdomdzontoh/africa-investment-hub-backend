"""Admin operations — status transitions, matches, audit, analytics (PRD §6.4)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.audit import AuditLog
from app.models.enums import (
    FundingType,
    ProjectStage,
    ProjectStatus,
    UserRole,
    UserStatus,
)
from app.models.investor import InvestorProfile
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.integration


async def _investor(db) -> tuple[User, InvestorProfile]:
    user = User(clerk_id=f"c_{uuid.uuid4().hex}", role=UserRole.investor, status=UserStatus.pending)
    db.add(user)
    await db.flush()
    profile = InvestorProfile(user_id=user.id, company_name="Co", country_of_registration="GH")
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return user, profile


async def test_non_admin_forbidden(client, make_user, auth_as) -> None:
    auth_as(await make_user(role=UserRole.investor))
    resp = await client.get("/v1/admin/investors")
    assert resp.status_code == 403


async def test_admin_creates_project(client, db, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    resp = await client.post(
        "/v1/admin/projects",
        json={
            "title": "Admin-curated Hydro Plant",
            "sector": "Renewable Energy",
            "country": "KE",
            "brief_description": "A vetted opportunity added by the platform team.",
            "project_stage": "expansion",
            "funding_required": "8000000",
            "funding_type": "equity",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["owner_user_id"] == str(admin.id)


async def test_non_admin_cannot_create_admin_project(client, make_user, auth_as) -> None:
    auth_as(await make_user(role=UserRole.project_owner))
    resp = await client.post(
        "/v1/admin/projects",
        json={
            "title": "x",
            "sector": "Mining",
            "country": "ZA",
            "brief_description": "y",
            "project_stage": "concept",
            "funding_required": "1",
            "funding_type": "equity",
        },
    )
    assert resp.status_code == 403


async def test_invite_admin(client, db, make_user, auth_as, monkeypatch) -> None:
    from app.core import clerk_client

    calls: list[dict] = []

    async def fake_invite(*, email: str, role: str, redirect_url=None) -> None:
        calls.append({"email": email, "role": role})

    monkeypatch.setattr(clerk_client, "create_invitation", fake_invite)

    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    resp = await client.post("/v1/admin/users/invite", json={"email": "newadmin@example.com"})
    assert resp.status_code == 202
    assert calls == [{"email": "newadmin@example.com", "role": "admin"}]


async def test_invite_admin_forbidden_for_non_admin(client, make_user, auth_as) -> None:
    auth_as(await make_user(role=UserRole.investor))
    resp = await client.post("/v1/admin/users/invite", json={"email": "x@example.com"})
    assert resp.status_code == 403


async def test_approve_investor_writes_audit(client, db, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    _, profile = await _investor(db)

    auth_as(admin)
    resp = await client.patch(
        f"/v1/admin/investors/{profile.id}/status",
        json={"action": "approve", "reason": "looks good"},
    )
    assert resp.status_code == 200

    # User now approved.
    refreshed = await db.get(User, profile.user_id)
    await db.refresh(refreshed)
    assert refreshed.status == UserStatus.approved

    # Audit entry recorded.
    count = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "investor.approve")
    )
    assert count == 1


async def test_approve_project_requires_risk_level(client, db, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    owner = await make_user(role=UserRole.project_owner)
    project = Project(
        owner_user_id=owner.id,
        title="P",
        sector="Mining",
        country="ZA",
        brief_description="d",
        project_stage=ProjectStage.concept,
        funding_required=Decimal("1000"),
        funding_type=FundingType.equity,
        status=ProjectStatus.pending,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    auth_as(admin)
    # Missing risk_level → 422 validation.
    resp = await client.patch(
        f"/v1/admin/projects/{project.id}/status", json={"action": "approve"}
    )
    assert resp.status_code == 422

    resp = await client.patch(
        f"/v1/admin/projects/{project.id}/status",
        json={"action": "approve", "risk_level": "medium"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    assert resp.json()["risk_level"] == "medium"


async def test_create_manual_match(client, db, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    owner = await make_user(role=UserRole.project_owner)
    _, profile = await _investor(db)
    project = Project(
        owner_user_id=owner.id,
        title="P",
        sector="Tech",
        country="KE",
        brief_description="d",
        project_stage=ProjectStage.concept,
        funding_required=Decimal("1000"),
        funding_type=FundingType.equity,
        status=ProjectStatus.approved,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    auth_as(admin)
    resp = await client.post(
        "/v1/admin/matches",
        json={"investor_id": str(profile.id), "project_id": str(project.id)},
    )
    assert resp.status_code == 201
    assert resp.json()["source"] == "admin_manual"


async def test_analytics_overview(client, make_user, auth_as) -> None:
    auth_as(await make_user(role=UserRole.admin))
    resp = await client.get("/v1/admin/analytics")
    assert resp.status_code == 200
    assert "total_users" in resp.json()


async def test_analytics_counts_are_role_filtered(client, make_user, auth_as) -> None:
    """Admins and facilitators must never be counted as investors (the bug
    behind mismatched dashboard figures)."""
    admin = await make_user(role=UserRole.admin)
    await make_user(role=UserRole.investor, status=UserStatus.approved)
    await make_user(role=UserRole.investor, status=UserStatus.pending)
    await make_user(role=UserRole.project_owner, status=UserStatus.approved)

    auth_as(admin)
    resp = await client.get("/v1/admin/analytics")
    assert resp.status_code == 200
    data = resp.json()

    assert sum(data["investors_by_status"].values()) == 2
    assert data["users_by_role"]["investor"] == 2
    assert data["users_by_role"]["project_owner"] == 1
    assert data["users_by_role"]["admin"] == 1
    assert data["total_users"] == 4
