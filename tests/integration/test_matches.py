"""Investor-facing match actions — interest, dismiss, confidential (PRD §12.3)."""

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


async def _make_project(db, *, owner: User) -> Project:
    project = Project(
        owner_user_id=owner.id,
        title="Solar Farm Ghana",
        sector="Renewable Energy",
        country="GH",
        brief_description="A 50MW solar project.",
        project_stage=ProjectStage.expansion,
        funding_required=Decimal("5000000"),
        funding_type=FundingType.equity,
        status=ProjectStatus.approved,
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


async def _make_match(db, *, investor: InvestorProfile, project: Project, status) -> Match:
    match = Match(
        investor_id=investor.id,
        project_id=project.id,
        score=0.91,
        explanation="Strong sector and ticket-size fit.",
        source=MatchSource.ai_generated,
        status=status,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)
    return match


async def test_matches_list_includes_project(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    await _make_match(db, investor=profile, project=project, status=MatchStatus.investor_notified)

    auth_as(investor_user)
    resp = await client.get("/v1/investors/me/matches")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["project"]["title"] == "Solar Farm Ghana"
    assert item["score"] == pytest.approx(0.91)


async def test_express_interest_transitions_status(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.investor_notified
    )

    auth_as(investor_user)
    resp = await client.post(f"/v1/matches/{match.id}/interest")
    assert resp.status_code == 200
    assert resp.json()["status"] == "investor_interested"


async def test_express_interest_twice_conflicts(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.investor_interested
    )

    auth_as(investor_user)
    resp = await client.post(f"/v1/matches/{match.id}/interest")
    assert resp.status_code == 409


async def test_dismiss_hides_match_from_list(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.investor_notified
    )

    auth_as(investor_user)
    resp = await client.post(f"/v1/matches/{match.id}/dismiss")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"

    resp = await client.get("/v1/investors/me/matches")
    assert resp.json()["items"] == []


async def test_cannot_act_on_another_investors_match(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    _, profile_a = await _make_investor(db)
    investor_b, _ = await _make_investor(db)
    match = await _make_match(
        db, investor=profile_a, project=project, status=MatchStatus.investor_notified
    )

    auth_as(investor_b)
    resp = await client.post(f"/v1/matches/{match.id}/interest")
    assert resp.status_code == 403


async def test_confidential_toggle(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.investor_notified
    )

    auth_as(investor_user)
    resp = await client.patch(
        f"/v1/matches/{match.id}/confidential", json={"confidential": True}
    )
    assert resp.status_code == 200
    assert resp.json()["is_confidential"] is True
