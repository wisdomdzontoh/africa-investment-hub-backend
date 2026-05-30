"""CMS country content + public localisation + versioning (PRD §6.4, §7)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.country import CountryContentVersion
from app.models.enums import UserRole

pytestmark = pytest.mark.integration


async def test_publish_then_public_localised(client, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)

    payload = {
        "country_name": "Ghana",
        "region": "West Africa",
        "foreign_ownership_rules": {
            "en": "Foreigners may own up to 100%.",
            "fr": "Les étrangers peuvent détenir 100%.",
        },
        "publish": True,
    }
    resp = await client.put("/v1/admin/cms/countries/GH", json=payload)
    assert resp.status_code == 200
    assert resp.json()["is_published"] is True

    # Public list (no auth) shows the published country.
    auth_as(None)
    resp = await client.get("/v1/countries")
    assert resp.status_code == 200
    assert any(c["country_code"] == "GH" for c in resp.json())

    # Public detail in French returns the French variant.
    resp = await client.get("/v1/countries/GH", headers={"Accept-Language": "fr"})
    assert resp.status_code == 200
    assert resp.json()["foreign_ownership_rules"] == "Les étrangers peuvent détenir 100%."

    # Missing locale falls back to English.
    resp = await client.get("/v1/countries/GH", headers={"Accept-Language": "zh"})
    assert resp.json()["foreign_ownership_rules"] == "Foreigners may own up to 100%."


async def test_unpublished_country_not_public(client, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    await client.put(
        "/v1/admin/cms/countries/NG",
        json={"country_name": "Nigeria", "publish": False},
    )
    auth_as(None)
    resp = await client.get("/v1/countries/NG")
    assert resp.status_code == 404


async def test_versions_created_on_edit(client, db, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    await client.put("/v1/admin/cms/countries/KE", json={"country_name": "Kenya"})
    await client.put(
        "/v1/admin/cms/countries/KE",
        json={"country_name": "Kenya", "tax_system": {"en": "30% CIT"}},
    )
    # Second save snapshots the first state.
    count = await db.scalar(
        select(func.count()).select_from(CountryContentVersion).where(
            CountryContentVersion.country_code == "KE"
        )
    )
    assert count >= 1


async def test_homepage_get_and_update(client, make_user, auth_as) -> None:
    admin = await make_user(role=UserRole.admin)
    auth_as(admin)
    resp = await client.get("/v1/admin/cms/homepage")
    assert resp.status_code == 200
    resp = await client.put(
        "/v1/admin/cms/homepage",
        json={"stats": [{"label": {"en": "Countries"}, "value": "54"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["stats"][0]["value"] == "54"
