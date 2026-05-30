"""Document presign + contact form (covers storage validation + email path)."""

from __future__ import annotations

import pytest

from app.models.enums import UserRole

pytestmark = pytest.mark.integration

_INTAKE = {"company_name": "Acme", "country_of_registration": "US"}


async def test_investor_document_presign(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    await client.post("/v1/investors/register", json=_INTAKE)

    resp = await client.post(
        "/v1/investors/me/documents",
        json={
            "filename": "aml_certificate.pdf",
            "content_type": "application/pdf",
            "doc_type": "aml_certificate",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["r2_key"].startswith("investor/")
    assert body["upload_url"].startswith("https://r2.test/put/")


async def test_presign_rejects_bad_content_type(client, make_user, auth_as) -> None:
    user = await make_user(role=UserRole.investor)
    auth_as(user)
    await client.post("/v1/investors/register", json=_INTAKE)
    resp = await client.post(
        "/v1/investors/me/documents",
        json={"filename": "x.exe", "content_type": "application/x-msdownload", "doc_type": "other"},
    )
    assert resp.status_code == 422


async def test_contact_form(client, auth_as) -> None:
    auth_as(None)
    resp = await client.post(
        "/v1/contact",
        json={"name": "Jane", "email": "jane@example.com", "message": "Hello there."},
    )
    assert resp.status_code == 200
    assert "in touch" in resp.json()["message"].lower()
