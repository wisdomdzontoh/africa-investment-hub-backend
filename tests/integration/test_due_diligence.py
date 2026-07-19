"""Due-diligence workflow — request, evidence upload, admin sign-off (PRD §6.8)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.enums import (
    FundingType,
    MatchSource,
    MatchStatus,
    ProjectStage,
    ProjectStatus,
    UserRole,
    UserStatus,
)
from app.models.investor import InvestorProfile
from app.models.match import Match
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.integration


async def _setup(db, *, match_status=MatchStatus.nda_signed):
    owner = User(clerk_id=f"c_{uuid.uuid4().hex}", role=UserRole.project_owner)
    db.add(owner)
    await db.flush()
    project = Project(
        owner_user_id=owner.id,
        title="Solar Farm",
        sector="Renewable Energy",
        country="GH",
        brief_description="50MW.",
        project_stage=ProjectStage.expansion,
        funding_required=Decimal("5000000"),
        funding_type=FundingType.equity,
        status=ProjectStatus.approved,
    )
    db.add(project)
    investor_user = User(
        clerk_id=f"c_{uuid.uuid4().hex}", role=UserRole.investor, status=UserStatus.approved
    )
    db.add(investor_user)
    await db.flush()
    profile = InvestorProfile(
        user_id=investor_user.id, company_name="Acme", country_of_registration="US"
    )
    db.add(profile)
    await db.flush()
    match = Match(
        investor_id=profile.id,
        project_id=project.id,
        source=MatchSource.ai_generated,
        status=match_status,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)
    await db.refresh(investor_user)
    return investor_user, match


async def test_request_requires_nda(client, db, auth_as) -> None:
    investor_user, match = await _setup(db, match_status=MatchStatus.investor_interested)
    auth_as(investor_user)
    resp = await client.post(f"/v1/matches/{match.id}/due-diligence")
    assert resp.status_code == 403


async def test_request_creates_checklist(client, db, auth_as) -> None:
    investor_user, match = await _setup(db)
    auth_as(investor_user)
    resp = await client.post(f"/v1/matches/{match.id}/due-diligence")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "requested"
    assert len(body["checklist"]) > 0
    assert all(item["status"] == "pending" for item in body["checklist"])

    # Idempotency: a second request conflicts.
    assert (await client.post(f"/v1/matches/{match.id}/due-diligence")).status_code == 409


async def test_upload_evidence_and_signoff(client, db, make_user, auth_as) -> None:
    investor_user, match = await _setup(db)
    auth_as(investor_user)
    dd = (await client.post(f"/v1/matches/{match.id}/due-diligence")).json()
    item_id = dd["checklist"][0]["item_id"]

    # Investor uploads evidence → item becomes submitted, request in_progress.
    resp = await client.post(
        f"/v1/due-diligence/{dd['id']}/items/{item_id}/document",
        json={"filename": "incorp.pdf", "content_type": "application/pdf", "doc_type": "legal"},
    )
    assert resp.status_code == 200
    assert "upload_url" in resp.json()

    got = (await client.get(f"/v1/matches/{match.id}/due-diligence")).json()
    submitted = next(i for i in got["checklist"] if i["item_id"] == item_id)
    assert submitted["status"] == "submitted"
    assert got["status"] == "in_progress"

    # Investor can't sign off (admin only).
    assert (
        await client.patch(
            f"/v1/due-diligence/{dd['id']}/items/{item_id}", json={"status": "approved"}
        )
    ).status_code == 403

    # Admin signs the item off.
    auth_as(await make_user(role=UserRole.admin))
    resp = await client.patch(
        f"/v1/due-diligence/{dd['id']}/items/{item_id}", json={"status": "approved"}
    )
    assert resp.status_code == 200
    approved = next(i for i in resp.json()["checklist"] if i["item_id"] == item_id)
    assert approved["status"] == "approved"


async def test_outsider_cannot_view_dd(client, db, make_user, auth_as) -> None:
    investor_user, match = await _setup(db)
    auth_as(investor_user)
    await client.post(f"/v1/matches/{match.id}/due-diligence")

    auth_as(await make_user(role=UserRole.investor))
    assert (await client.get(f"/v1/matches/{match.id}/due-diligence")).status_code == 403
