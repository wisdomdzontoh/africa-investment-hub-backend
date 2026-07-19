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


async def test_browse_interest_creates_match_and_notifies(
    client, db, make_user, auth_as
) -> None:
    """Investor expresses interest from the catalogue — no prior match needed.
    The facilitator and every admin get an in-app notification."""
    from app.models.notification import Notification

    owner = await make_user(role=UserRole.project_owner)
    admin = await make_user(role=UserRole.admin)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)

    auth_as(investor_user)
    resp = await client.post(f"/v1/projects/{project.id}/interest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "investor_interested"
    assert body["source"] == "investor_initiated"

    # Idempotent: second call returns the same match, unchanged.
    resp2 = await client.post(f"/v1/projects/{project.id}/interest")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == body["id"]

    from sqlalchemy import select

    rows = (await db.execute(select(Notification))).scalars().all()
    recipients = {str(n.user_id) for n in rows if n.type == "project_interest"}
    assert str(owner.id) in recipients
    assert str(admin.id) in recipients
    # No duplicate notifications from the idempotent second call.
    assert len([n for n in rows if n.type == "project_interest"]) == 2


async def test_browse_interest_requires_approved_investor(
    client, db, make_user, auth_as
) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)

    # Pending investor is blocked.
    pending_user, _ = await _make_investor(db, status=UserStatus.pending)
    auth_as(pending_user)
    resp = await client.post(f"/v1/projects/{project.id}/interest")
    assert resp.status_code == 403

    # Facilitators cannot express interest.
    auth_as(owner)
    resp = await client.post(f"/v1/projects/{project.id}/interest")
    assert resp.status_code == 403


async def test_browse_interest_advances_existing_match(
    client, db, make_user, auth_as
) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.investor_notified
    )

    auth_as(investor_user)
    resp = await client.post(f"/v1/projects/{project.id}/interest")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(match.id)
    assert resp.json()["status"] == "investor_interested"


async def test_facilitator_sees_interested_investors(client, db, make_user, auth_as) -> None:
    """Facilitators see engaged matches on their projects — with the investor
    identity withheld on confidential engagements (PRD §6.9)."""
    owner = await make_user(role=UserRole.project_owner)
    other_owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    other_project = await _make_project(db, owner=other_owner)

    _, open_profile = await _make_investor(db)
    _, secret_profile = await _make_investor(db)
    _, quiet_profile = await _make_investor(db)

    await _make_match(
        db, investor=open_profile, project=project, status=MatchStatus.investor_interested
    )
    confidential = await _make_match(
        db, investor=secret_profile, project=project, status=MatchStatus.investor_interested
    )
    confidential.is_confidential = True
    # Pre-interest stages stay internal; other facilitators' matches invisible.
    await _make_match(
        db, investor=quiet_profile, project=project, status=MatchStatus.investor_notified
    )
    await _make_match(
        db, investor=open_profile, project=other_project, status=MatchStatus.investor_interested
    )
    await db.commit()

    auth_as(owner)
    resp = await client.get("/v1/projects/mine/matches")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2

    by_conf = {item["is_confidential"]: item for item in items}
    assert by_conf[False]["investor"]["company_name"] == "Acme Capital"
    assert by_conf[False]["project_title"] == "Solar Farm Ghana"
    assert by_conf[True]["investor"] is None

    # Investors cannot use the facilitator endpoint.
    investor_user, _ = await _make_investor(db)
    auth_as(investor_user)
    resp = await client.get("/v1/projects/mine/matches")
    assert resp.status_code == 403


async def test_notify_matching_investors_task(db, make_user, monkeypatch) -> None:
    """New approved project → investors with sector/country overlap get an
    in-app alert; others don't."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.notification import Notification
    from app.workers import tasks

    monkeypatch.setattr(
        tasks, "SessionLocal", async_sessionmaker(bind=db.bind, expire_on_commit=False)
    )

    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)  # sector "Renewable Energy"

    matching_user, matching_profile = await _make_investor(db)
    matching_profile.investment_sectors = ["Renewable Energy"]
    other_user, other_profile = await _make_investor(db)
    other_profile.investment_sectors = ["Mining"]
    other_profile.investment_countries = ["ke"]
    await db.commit()

    count = await tasks.notify_matching_investors({}, str(project.id))
    assert count == 1

    rows = (await db.execute(select(Notification))).scalars().all()
    alerts = [n for n in rows if n.type == "new_project"]
    assert len(alerts) == 1
    assert alerts[0].user_id == matching_user.id
    assert alerts[0].link == f"/opportunities/{project.id}"


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


async def test_deal_room_gates_full_description(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    project.executive_summary = "Exec summary."
    project.full_description = "PRIVILEGED full plan."
    project.documents = [{"type": "business_plan", "filename": "plan.pdf", "r2_key": "k/plan.pdf"}]
    await db.commit()
    investor_user, profile = await _make_investor(db)

    # Before NDA: interested → exec summary visible, full description + docs gated.
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.investor_interested
    )
    auth_as(investor_user)
    body = (await client.get(f"/v1/matches/{match.id}/deal-room")).json()
    assert body["nda_unlocked"] is False
    assert body["project"]["full_description"] is None
    assert body["project"]["documents"] == []

    # NDA signed → full description + documents unlocked.
    match.status = MatchStatus.nda_signed
    await db.commit()
    body = (await client.get(f"/v1/matches/{match.id}/deal-room")).json()
    assert body["nda_unlocked"] is True
    assert body["project"]["full_description"] == "PRIVILEGED full plan."
    assert len(body["project"]["documents"]) == 1


async def test_nda_sign_flow(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.nda_sent
    )

    auth_as(investor_user)
    # can_sign_nda surfaced while awaiting signature.
    assert (await client.get(f"/v1/matches/{match.id}/deal-room")).json()["can_sign_nda"] is True

    resp = await client.post(f"/v1/matches/{match.id}/nda/sign")
    assert resp.status_code == 200
    assert resp.json()["status"] == "nda_signed"

    # Signing again is a conflict (no NDA pending).
    assert (await client.post(f"/v1/matches/{match.id}/nda/sign")).status_code == 409


async def test_nda_pdf_renders(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.nda_sent
    )

    auth_as(investor_user)
    resp = await client.get(f"/v1/matches/{match.id}/nda.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"

    # MOU isn't available until the deal reaches the MOU stage.
    assert (await client.get(f"/v1/matches/{match.id}/mou.pdf")).status_code == 403


async def test_deal_room_forbidden_for_outsider(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    _, profile = await _make_investor(db)
    outsider, _ = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.nda_signed
    )

    auth_as(outsider)
    assert (await client.get(f"/v1/matches/{match.id}/deal-room")).status_code == 403


async def test_deal_room_document_requires_nda(client, db, make_user, auth_as) -> None:
    owner = await make_user(role=UserRole.project_owner)
    project = await _make_project(db, owner=owner)
    project.documents = [{"type": "business_plan", "filename": "plan.pdf", "r2_key": "k/plan.pdf"}]
    await db.commit()
    investor_user, profile = await _make_investor(db)
    match = await _make_match(
        db, investor=profile, project=project, status=MatchStatus.investor_interested
    )

    auth_as(investor_user)
    # Gated before NDA.
    assert (
        await client.get(f"/v1/matches/{match.id}/documents/k/plan.pdf")
    ).status_code == 403

    match.status = MatchStatus.nda_signed
    await db.commit()
    resp = await client.get(f"/v1/matches/{match.id}/documents/k/plan.pdf")
    assert resp.status_code == 200
    assert "url" in resp.json()


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
