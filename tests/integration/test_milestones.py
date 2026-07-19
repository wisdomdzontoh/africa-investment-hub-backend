"""Project monitoring milestones — access control + CRUD (PRD §6.6)."""

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


async def _make_investor_with_match(db, project, *, status) -> User:
    user = User(clerk_id=f"c_{uuid.uuid4().hex}", role=UserRole.investor, status=UserStatus.approved)
    db.add(user)
    await db.flush()
    profile = InvestorProfile(
        user_id=user.id, company_name="Acme Capital", country_of_registration="US"
    )
    db.add(profile)
    await db.flush()
    db.add(
        Match(
            investor_id=profile.id,
            project_id=project.id,
            source=MatchSource.ai_generated,
            status=status,
        )
    )
    await db.commit()
    await db.refresh(user)
    return user


async def test_owner_creates_and_lists_milestone(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)

    auth_as(owner)
    resp = await client.post(
        f"/v1/projects/{project.id}/milestones",
        json={"title": "Site acquisition", "status": "in_progress", "due_date": "2026-09-30"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "Site acquisition"

    resp = await client.get(f"/v1/projects/{project.id}/milestones")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_owner_updates_and_deletes_milestone(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)

    auth_as(owner)
    created = (
        await client.post(
            f"/v1/projects/{project.id}/milestones", json={"title": "Permitting"}
        )
    ).json()

    resp = await client.patch(
        f"/v1/milestones/{created['id']}", json={"status": "completed"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    resp = await client.delete(f"/v1/milestones/{created['id']}")
    assert resp.status_code == 200
    assert (await client.get(f"/v1/projects/{project.id}/milestones")).json() == []


async def test_other_facilitator_cannot_manage(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    other = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)

    auth_as(other)
    resp = await client.post(
        f"/v1/projects/{project.id}/milestones", json={"title": "Hijack"}
    )
    assert resp.status_code == 403


async def test_engaged_investor_can_view_not_manage(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    auth_as(owner)
    await client.post(f"/v1/projects/{project.id}/milestones", json={"title": "Groundbreaking"})

    investor = await _make_investor_with_match(db, project, status=MatchStatus.nda_signed)
    auth_as(investor)
    resp = await client.get(f"/v1/projects/{project.id}/milestones")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = await client.post(
        f"/v1/projects/{project.id}/milestones", json={"title": "Investor edit"}
    )
    assert resp.status_code == 403


async def test_unrelated_investor_cannot_view(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor = await make_user(role=UserRole.investor)

    auth_as(investor)
    resp = await client.get(f"/v1/projects/{project.id}/milestones")
    assert resp.status_code == 403


async def test_admin_can_manage(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    admin = await make_user(role=UserRole.admin)
    project = await _make_project(db, owner=owner)

    auth_as(admin)
    resp = await client.post(
        f"/v1/projects/{project.id}/milestones", json={"title": "Admin note"}
    )
    assert resp.status_code == 201
