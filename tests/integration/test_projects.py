"""Project endpoints — listing, NDA gate, and ownership (PRD §6.3, §6.10)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.enums import (
    FundingType,
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


async def _make_project(db, *, owner: User, status=ProjectStatus.approved) -> Project:
    project = Project(
        owner_user_id=owner.id,
        title="Solar Farm Ghana",
        sector="Renewable Energy",
        country="GH",
        brief_description="A 50MW solar project.",
        executive_summary="Executive summary visible to approved investors.",
        full_description="PRIVILEGED full description behind the NDA gate.",
        project_stage=ProjectStage.expansion,
        funding_required=Decimal("5000000"),
        funding_type=FundingType.equity,
        status=status,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _make_investor(db, *, status=UserStatus.approved) -> tuple[User, InvestorProfile]:
    user = User(clerk_id=f"c_{uuid.uuid4().hex}", role=UserRole.investor, status=status)
    db.add(user)
    await db.flush()
    profile = InvestorProfile(
        user_id=user.id, company_name="Acme Capital", country_of_registration="US"
    )
    db.add(profile)
    await db.commit()
    await db.refresh(user)
    await db.refresh(profile)
    return user, profile


async def test_list_only_approved(client, db, make_user) -> None:
    owner = await make_user(role=UserRole.project_owner)
    await _make_project(db, owner=owner, status=ProjectStatus.approved)
    await _make_project(db, owner=owner, status=ProjectStatus.pending)

    resp = await client.get("/v1/projects")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1


async def test_detail_anonymous_sees_no_gated_fields(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)

    auth_as(None)
    resp = await client.get(f"/v1/projects/{project.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["executive_summary"] is None
    assert body["full_description"] is None


async def test_detail_approved_investor_sees_summary_not_full(client, db, auth_as) -> None:
    owner = User(clerk_id=f"c_{uuid.uuid4().hex}", role=UserRole.project_owner)
    db.add(owner)
    await db.commit()
    project = await _make_project(db, owner=owner)
    investor_user, _ = await _make_investor(db)

    auth_as(investor_user)
    resp = await client.get(f"/v1/projects/{project.id}")
    body = resp.json()
    assert body["executive_summary"] is not None
    # No match → full description stays gated.
    assert body["full_description"] is None


async def test_nda_gate_unlocks_full_description(client, db, auth_as) -> None:
    owner = User(clerk_id=f"c_{uuid.uuid4().hex}", role=UserRole.project_owner)
    db.add(owner)
    await db.commit()
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)

    # Match below the NDA threshold → still gated.
    match = Match(
        investor_id=profile.id, project_id=project.id, status=MatchStatus.investor_interested
    )
    db.add(match)
    await db.commit()

    auth_as(investor_user)
    resp = await client.get(f"/v1/projects/{project.id}")
    assert resp.json()["full_description"] is None

    # Advance to nda_signed → unlocked.
    match.status = MatchStatus.nda_signed
    await db.commit()

    resp = await client.get(f"/v1/projects/{project.id}")
    assert resp.json()["full_description"] == "PRIVILEGED full description behind the NDA gate."


async def test_owner_can_submit_project(client, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    auth_as(owner)
    payload = {
        "title": "Cassava Processing Plant",
        "sector": "Agriculture",
        "country": "NG",
        "brief_description": "Processing facility.",
        "project_stage": "revenue_generating",
        "funding_required": "2000000",
        "funding_type": "debt",
    }
    resp = await client.post("/v1/projects", json=payload)
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"


async def test_investor_cannot_submit_project(client, make_user, auth_as) -> None:
    investor = await make_user(role=UserRole.investor)
    auth_as(investor)
    resp = await client.post(
        "/v1/projects",
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


async def test_offset_paging_returns_total(client, db, make_user) -> None:
    owner = await make_user(role=UserRole.project_owner)
    for _ in range(3):
        await _make_project(db, owner=owner, status=ProjectStatus.approved)
    await _make_project(db, owner=owner, status=ProjectStatus.pending)

    resp = await client.get("/v1/projects?page=1&limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["has_more"] is True

    resp = await client.get("/v1/projects?page=2&limit=2")
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False


async def test_featured_filter_and_funding_sort(client, db, make_user) -> None:
    owner = await make_user(role=UserRole.project_owner)
    small = await _make_project(db, owner=owner)
    small.funding_required = Decimal("1000000")
    big = await _make_project(db, owner=owner)
    big.funding_required = Decimal("9000000")
    big.is_featured = True
    await db.commit()

    resp = await client.get("/v1/projects?featured=true")
    items = resp.json()["items"]
    assert [i["id"] for i in items] == [str(big.id)]

    resp = await client.get("/v1/projects?sort=funding_asc")
    items = resp.json()["items"]
    assert [i["id"] for i in items] == [str(small.id), str(big.id)]


async def test_owner_detail_returns_status_and_documents(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner, status=ProjectStatus.pending)

    auth_as(owner)
    resp = await client.get(f"/v1/projects/mine/{project.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["documents"] == []
    # Owner sees their own gated fields in full.
    assert body["full_description"] == "PRIVILEGED full description behind the NDA gate."


async def test_owner_detail_forbidden_for_others(client, db, make_user, auth_as) -> None:
    owner_a = await make_user(role=UserRole.project_owner)
    owner_b = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner_a)

    auth_as(owner_b)
    resp = await client.get(f"/v1/projects/mine/{project.id}")
    assert resp.status_code == 403


async def test_owner_can_update_own_project(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner, status=ProjectStatus.pending)

    auth_as(owner)
    resp = await client.patch(
        f"/v1/projects/{project.id}",
        json={"title": "Solar Farm Ghana — Phase II", "expected_roi_min": "12.5"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Solar Farm Ghana — Phase II"
    # Numeric(…, 2) pads the scale — compare numerically, not textually.
    assert Decimal(body["expected_roi_min"]) == Decimal("12.5")


async def test_owner_cannot_edit_others_project(client, db, make_user, auth_as) -> None:
    owner_a = await make_user(role=UserRole.project_owner)
    owner_b = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner_a)

    auth_as(owner_b)
    resp = await client.patch(f"/v1/projects/{project.id}", json={"title": "hijacked"})
    assert resp.status_code == 403
