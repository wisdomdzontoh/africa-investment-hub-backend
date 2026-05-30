"""Unit tests for Clerk claim/role extraction."""

from __future__ import annotations

from app.core.security import _extract_role
from app.models.enums import UserRole


def test_role_from_top_level() -> None:
    assert _extract_role({"role": "admin"}) == UserRole.admin


def test_role_from_public_metadata_snake() -> None:
    assert _extract_role({"public_metadata": {"role": "investor"}}) == UserRole.investor


def test_role_from_public_metadata_camel() -> None:
    assert _extract_role({"publicMetadata": {"role": "project_owner"}}) == UserRole.project_owner


def test_unknown_role_returns_none() -> None:
    assert _extract_role({"role": "superuser"}) is None


def test_missing_role_returns_none() -> None:
    assert _extract_role({}) is None
