"""Document download presign endpoints + AI risk assessment (P2-08)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

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

_DOC = {"type": "business_plan", "filename": "plan.pdf", "r2_key": "project/x/plan.pdf"}


async def _project(db, owner: User) -> Project:
    project = Project(
        owner_user_id=owner.id,
        title="Solar",
        sector="Renewable Energy",
        country="GH",
        brief_description="b",
        project_stage=ProjectStage.concept,
        funding_required=Decimal("1000000"),
        funding_type=FundingType.equity,
        status=ProjectStatus.approved,
        documents=[_DOC],
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def test_owner_and_admin_download_project_doc(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _project(db, owner)

    auth_as(owner)
    resp = await client.get(f"/v1/projects/{project.id}/documents/{_DOC['r2_key']}")
    assert resp.status_code == 200
    assert "url" in resp.json()

    auth_as(await make_user(role=UserRole.admin))
    assert (
        await client.get(f"/v1/projects/{project.id}/documents/{_DOC['r2_key']}")
    ).status_code == 200


async def test_other_owner_cannot_download_project_doc(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _project(db, owner)
    auth_as(await make_user(role=UserRole.project_owner))
    assert (
        await client.get(f"/v1/projects/{project.id}/documents/{_DOC['r2_key']}")
    ).status_code == 403


async def test_unknown_key_is_404(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _project(db, owner)
    auth_as(owner)
    assert (
        await client.get(f"/v1/projects/{project.id}/documents/nope/missing.pdf")
    ).status_code == 404


async def test_investor_downloads_own_and_admin_downloads_investor_doc(
    client, db, make_user, auth_as
) -> None:
    user = await make_user(role=UserRole.investor, status=UserStatus.approved)
    profile = InvestorProfile(
        user_id=user.id,
        company_name="Acme",
        country_of_registration="US",
        documents=[{"type": "aml", "filename": "aml.pdf", "r2_key": "investor/y/aml.pdf"}],
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    auth_as(user)
    assert (await client.get("/v1/investors/me/documents/investor/y/aml.pdf")).status_code == 200

    auth_as(await make_user(role=UserRole.admin))
    resp = await client.get(
        f"/v1/admin/investors/{profile.id}/documents/investor/y/aml.pdf"
    )
    assert resp.status_code == 200
    assert "url" in resp.json()


async def test_admin_risk_assessment(client, db, make_user, auth_as, monkeypatch) -> None:
    from app.services.ai import risk as risk_service

    async def fake_assess(db_, project_id):
        project = await db_.get(Project, project_id)
        project.admin_notes = "AI risk: medium"
        await db_.flush()
        return {"overall": "medium", "factors": ["currency"]}

    monkeypatch.setattr(risk_service, "assess", fake_assess)

    owner = await make_user(role=UserRole.project_owner)
    project = await _project(db, owner)
    auth_as(await make_user(role=UserRole.admin))
    resp = await client.post(f"/v1/admin/projects/{project.id}/risk-assessment")
    assert resp.status_code == 200
    body = resp.json()
    assert body["assessment"]["overall"] == "medium"
    assert "AI risk" in body["admin_notes"]
