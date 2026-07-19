"""Consultant registration + investor-only discovery (PRD §6.11)."""

from __future__ import annotations

import pytest
from app.models.consultant import ConsultantProfile
from app.models.enums import ConsultantStatus, UserRole, UserStatus

# The consultant feature is parked (DEC-3) and its router is unmounted in
# app/api/v1/router.py, so these endpoints 404 by design. Unskip when revived.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="Consultant feature parked (DEC-3); router unmounted."),
]

_PROFILE = {
    "full_name": "Ama Mensah",
    "country": "GH",
    "city": "Accra",
    "expertise_areas": ["Quantity Surveying"],
    "sectors_served": ["Construction"],
    "years_of_experience": 12,
}


async def test_register_consultant(client, make_user, auth_as) -> None:
    auth_as(await make_user(role=UserRole.project_owner))
    resp = await client.post("/v1/consultants/register", json=_PROFILE)
    assert resp.status_code == 201
    assert resp.json()["full_name"] == "Ama Mensah"


async def test_search_requires_approved_investor(client, make_user, auth_as) -> None:
    # Pending investor cannot search.
    auth_as(await make_user(role=UserRole.investor, status=UserStatus.pending))
    resp = await client.get("/v1/consultants")
    assert resp.status_code == 403


async def test_approved_investor_search_returns_only_approved(
    client, db, make_user, auth_as
) -> None:
    consultant_user = await make_user(role=UserRole.project_owner)
    approved = ConsultantProfile(
        user_id=consultant_user.id,
        full_name="Approved Consultant",
        country="GH",
        expertise_areas=["Legal Advisory"],
        sectors_served=["Real Estate"],
        status=ConsultantStatus.approved,
    )
    db.add(approved)
    pending_user = await make_user(role=UserRole.project_owner)
    pending = ConsultantProfile(
        user_id=pending_user.id,
        full_name="Pending Consultant",
        country="GH",
        status=ConsultantStatus.pending,
    )
    db.add(pending)
    await db.commit()

    auth_as(await make_user(role=UserRole.investor, status=UserStatus.approved))
    resp = await client.get("/v1/consultants")
    assert resp.status_code == 200
    names = [c["full_name"] for c in resp.json()["items"]]
    assert "Approved Consultant" in names
    assert "Pending Consultant" not in names


async def test_search_filter_by_expertise(client, db, make_user, auth_as) -> None:
    u = await make_user(role=UserRole.project_owner)
    db.add(
        ConsultantProfile(
            user_id=u.id,
            full_name="Surveyor",
            country="NG",
            expertise_areas=["Quantity Surveying"],
            sectors_served=["Construction"],
            status=ConsultantStatus.approved,
        )
    )
    await db.commit()

    auth_as(await make_user(role=UserRole.investor, status=UserStatus.approved))
    resp = await client.get("/v1/consultants", params={"expertise": "Quantity Surveying"})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1

    resp = await client.get("/v1/consultants", params={"expertise": "Mining"})
    assert len(resp.json()["items"]) == 0
