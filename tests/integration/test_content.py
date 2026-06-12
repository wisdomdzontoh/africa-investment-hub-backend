"""Public site content endpoints — homepage CMS + project counts (PRD §6.1)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.enums import FundingType, ProjectStage, ProjectStatus, UserRole
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.integration


async def _make_project(db, *, owner: User, country: str, status=ProjectStatus.approved) -> Project:
    project = Project(
        owner_user_id=owner.id,
        title=f"Project {uuid.uuid4().hex[:6]}",
        sector="Agriculture",
        country=country,
        brief_description="Brief.",
        project_stage=ProjectStage.concept,
        funding_required=Decimal("1000000"),
        funding_type=FundingType.equity,
        status=status,
    )
    db.add(project)
    await db.commit()
    return project


async def test_homepage_content_defaults(client) -> None:
    resp = await client.get("/v1/content/homepage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"] == []
    assert body["partner_logos"] == []


async def test_homepage_content_reflects_admin_edit(client, db, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    payload = {"stats": [{"value": "$3.4T", "label": {"en": "Combined GDP"}}]}
    resp = await client.put("/v1/admin/cms/homepage", json=payload)
    assert resp.status_code == 200

    auth_as(None)
    resp = await client.get("/v1/content/homepage")
    assert resp.json()["stats"][0]["value"] == "$3.4T"


async def test_project_counts_by_country(client, db, make_user) -> None:
    owner = await make_user(role=UserRole.project_owner)
    await _make_project(db, owner=owner, country="GH")
    await _make_project(db, owner=owner, country="GH")
    await _make_project(db, owner=owner, country="KE")
    # Pending projects are not counted.
    await _make_project(db, owner=owner, country="NG", status=ProjectStatus.pending)

    resp = await client.get("/v1/content/project-counts")
    assert resp.status_code == 200
    counts = resp.json()["counts"]
    assert counts["GH"] == 2
    assert counts["KE"] == 1
    assert "NG" not in counts
