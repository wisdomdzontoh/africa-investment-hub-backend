"""Investor registration / profile endpoints (PRD §6.2, §6.5)."""

from __future__ import annotations

import pytest

from app.models.enums import UserRole

pytestmark = pytest.mark.integration

_INTAKE = {
    "company_name": "Acme Capital",
    "country_of_registration": "US",
    "registration_number": "RC-99887766",
    "investment_countries": ["GH", "NG"],
    "investment_sectors": ["Renewable Energy"],
    "risk_appetite": "medium",
}


async def test_register_creates_profile(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    resp = await client.post("/v1/investors/register", json=_INTAKE)
    assert resp.status_code == 201
    body = resp.json()
    assert body["company_name"] == "Acme Capital"


async def test_register_then_get_me(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    await client.post("/v1/investors/register", json=_INTAKE)
    resp = await client.get("/v1/investors/me")
    assert resp.status_code == 200
    assert resp.json()["country_of_registration"] == "US"


async def test_double_register_conflicts(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    await client.post("/v1/investors/register", json=_INTAKE)
    resp = await client.post("/v1/investors/register", json=_INTAKE)
    assert resp.status_code == 409


async def test_get_me_without_profile_404(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    resp = await client.get("/v1/investors/me")
    assert resp.status_code == 404


async def test_non_investor_cannot_register(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.project_owner)
    auth_as(user)
    resp = await client.post("/v1/investors/register", json=_INTAKE)
    assert resp.status_code == 403


async def test_update_preferences(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    await client.post("/v1/investors/register", json=_INTAKE)
    resp = await client.patch(
        "/v1/investors/me", json={"risk_appetite": "high", "time_horizon": "5 years"}
    )
    assert resp.status_code == 200
    assert resp.json()["risk_appetite"] == "high"


async def test_registration_number_encrypted_at_rest(client, db, make_user, auth_as) -> None:
    from sqlalchemy import text

    user = await make_user(role=UserRole.investor)
    auth_as(user)
    await client.post("/v1/investors/register", json=_INTAKE)
    # Raw column value must not equal the plaintext.
    raw = await db.scalar(
        text("SELECT registration_number FROM investor_profiles LIMIT 1")
    )
    assert raw is not None
    assert raw != "RC-99887766"
