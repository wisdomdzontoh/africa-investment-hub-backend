"""Embedding text builders + persistence (PRD §12.3, §12.4).

Turns profiles/projects/consultants into the canonical text we embed, then
stores the resulting vector on the row.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consultant import ConsultantProfile
from app.models.investor import InvestorProfile
from app.models.project import Project
from app.services.ai import client


def build_profile_text(p: InvestorProfile) -> str:
    parts = [
        f"Investor {p.company_name} registered in {p.country_of_registration}.",
        f"Interested countries: {', '.join(p.investment_countries or [])}.",
        f"Sectors: {', '.join(p.investment_sectors or [])}.",
        f"Investment types: {', '.join(p.investment_types or [])}.",
        f"Ticket size {p.min_ticket_size}–{p.max_ticket_size}.",
        f"Risk appetite: {p.risk_appetite.value if p.risk_appetite else 'unknown'}.",
        f"Target ROI {p.target_roi_min}–{p.target_roi_max}.",
        f"Preferred ownership: {', '.join(p.preferred_ownership_structures or [])}.",
        f"Excluded sectors: {', '.join(p.sectors_excluded or [])}.",
        f"ESG: {p.esg_requirements or 'n/a'}.",
    ]
    return " ".join(parts)


def build_project_text(p: Project) -> str:
    parts = [
        f"Project {p.title} in {p.sector}, {p.country}.",
        f"Stage: {p.project_stage.value}.",
        p.brief_description or "",
        p.executive_summary or "",
        f"Funding required {p.funding_required} ({p.funding_type.value}).",
        f"Expected ROI {p.expected_roi_min}–{p.expected_roi_max}.",
        f"Use of funds: {p.use_of_funds or 'n/a'}.",
    ]
    return " ".join(parts)


def build_consultant_text(c: ConsultantProfile) -> str:
    parts = [
        f"Consultant {c.full_name}, {c.title or ''} in {c.city or ''}, {c.country}.",
        f"Expertise: {', '.join(c.expertise_areas or [])}.",
        f"Sectors served: {', '.join(c.sectors_served or [])}.",
        f"Experience: {c.years_of_experience or 0} years.",
        f"Languages: {', '.join(c.languages_spoken or [])}.",
        c.bio or "",
        c.key_achievements or "",
    ]
    return " ".join(parts)


async def embed_investor(db: AsyncSession, investor_id: uuid.UUID) -> None:
    profile = await db.get(InvestorProfile, investor_id)
    if profile is None:
        return
    profile.embedding = await client.embed(build_profile_text(profile))
    await db.flush()


async def embed_project(db: AsyncSession, project_id: uuid.UUID) -> None:
    project = await db.get(Project, project_id)
    if project is None:
        return
    project.embedding = await client.embed(build_project_text(project))
    await db.flush()


async def embed_consultant(db: AsyncSession, consultant_id: uuid.UUID) -> None:
    consultant = await db.get(ConsultantProfile, consultant_id)
    if consultant is None:
        return
    consultant.embedding = await client.embed(build_consultant_text(consultant))
    await db.flush()
