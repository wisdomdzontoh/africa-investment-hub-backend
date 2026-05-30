"""Homepage / general-pages CMS schemas (PRD §6.4)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class HomepageContentOut(ORMModel):
    stats: list[dict[str, Any]] = []
    process_steps: list[dict[str, Any]] = []
    sector_highlights: list[dict[str, Any]] = []
    partner_logos: list[dict[str, Any]] = []
    team_members: list[dict[str, Any]] = []
    advisory_board: list[dict[str, Any]] = []


class HomepageContentUpdate(BaseModel):
    stats: list[dict[str, Any]] | None = None
    process_steps: list[dict[str, Any]] | None = None
    sector_highlights: list[dict[str, Any]] | None = None
    partner_logos: list[dict[str, Any]] | None = None
    team_members: list[dict[str, Any]] | None = None
    advisory_board: list[dict[str, Any]] | None = None
