"""Health endpoint integration test."""

from __future__ import annotations

import pytest


@pytest.mark.integration
async def test_health_ok(client) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert body["status"] == "ok"
    assert "version" in body
