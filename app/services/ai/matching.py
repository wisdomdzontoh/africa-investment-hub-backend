"""AI matching engines (PRD §12.3, §12.4).

Two-stage: pgvector similarity narrows candidates, then GPT-4o re-ranks and
explains. Generated matches are written as ``ai_recommended`` — invisible to
the investor until an admin reviews them (human-in-the-loop, PRD §6.7).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_text import CONSULTANT_RERANK_PROMPT, MATCH_RERANK_PROMPT
from app.core.logging import get_logger
from app.models.consultant import ConsultantMatch, ConsultantProfile
from app.models.enums import (
    ConsultantStatus,
    MatchSource,
    MatchStatus,
    ProjectStatus,
)
from app.models.investor import InvestorProfile
from app.models.match import Match
from app.models.project import Project
from app.services.ai import client, embeddings

logger = get_logger(__name__)

_CANDIDATE_LIMIT = 20
_TOP_N = 5


async def generate_project_matches(db: AsyncSession, investor_id: uuid.UUID) -> int:
    """Generate AI project matches for an investor. Returns count created."""
    investor = await db.get(InvestorProfile, investor_id)
    if investor is None:
        return 0
    if investor.embedding is None:
        await embeddings.embed_investor(db, investor_id)
        investor = await db.get(InvestorProfile, investor_id)
        if investor is None or investor.embedding is None:
            return 0

    distance = Project.embedding.cosine_distance(investor.embedding)
    stmt = (
        select(Project, (1 - distance).label("score"))
        .where(Project.status == ProjectStatus.approved, Project.embedding.is_not(None))
        .order_by(distance.asc())
        .limit(_CANDIDATE_LIMIT)
    )
    candidates = (await db.execute(stmt)).all()
    if not candidates:
        return 0

    ranked = await _rerank_projects(investor, candidates)
    created = 0
    for item in ranked:
        project_id = item.get("project_id")
        if not project_id:
            continue
        try:
            pid = uuid.UUID(str(project_id))
        except ValueError:
            continue
        existing = await db.execute(
            select(Match).where(Match.investor_id == investor_id, Match.project_id == pid)
        )
        if existing.scalar_one_or_none() is not None:
            continue
        db.add(
            Match(
                investor_id=investor_id,
                project_id=pid,
                score=float(item.get("score", 0.0)),
                explanation=item.get("explanation"),
                source=MatchSource.ai_generated,
                status=MatchStatus.ai_recommended,
            )
        )
        created += 1
    await db.flush()
    return created


async def _rerank_projects(investor: InvestorProfile, candidates: list) -> list[dict]:
    profile_text = embeddings.build_profile_text(investor)
    candidate_lines = [
        f"- project_id={p.id} | {embeddings.build_project_text(p)[:400]}"
        for p, _score in candidates
    ]
    prompt = MATCH_RERANK_PROMPT.format(top_n=_TOP_N)
    content = await client.chat_completion(
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"INVESTOR:\n{profile_text}\n\nCANDIDATES:\n" + "\n".join(candidate_lines),
            },
        ],
        complex_query=True,
        trace_name="match_rerank",
        json_mode=True,
    )
    data = client.structured_json(content)
    return data.get("matches", []) if isinstance(data, dict) else []


async def generate_consultant_matches(
    db: AsyncSession, *, investor_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> int:
    """Match an investor to local consultants for their active project sectors."""
    investor = await db.get(InvestorProfile, investor_id)
    if investor is None or investor.embedding is None:
        return 0

    distance = ConsultantProfile.embedding.cosine_distance(investor.embedding)
    stmt = (
        select(ConsultantProfile)
        .where(
            ConsultantProfile.status == ConsultantStatus.approved,
            ConsultantProfile.embedding.is_not(None),
        )
        .order_by(distance.asc())
        .limit(10)
    )
    candidates = list((await db.execute(stmt)).scalars().all())
    if not candidates:
        return 0

    profile_text = embeddings.build_profile_text(investor)
    candidate_lines = [
        f"- consultant_id={c.id} | {embeddings.build_consultant_text(c)[:300]}"
        for c in candidates
    ]
    content = await client.chat_completion(
        messages=[
            {"role": "system", "content": CONSULTANT_RERANK_PROMPT.format(top_n=3)},
            {
                "role": "user",
                "content": f"INVESTOR:\n{profile_text}\n\nCONSULTANTS:\n" + "\n".join(candidate_lines),
            },
        ],
        complex_query=True,
        trace_name="consultant_rerank",
        json_mode=True,
    )
    data = client.structured_json(content)
    created = 0
    for item in data.get("matches", []) if isinstance(data, dict) else []:
        cid = item.get("consultant_id")
        if not cid:
            continue
        try:
            consultant_uuid = uuid.UUID(str(cid))
        except ValueError:
            continue
        db.add(
            ConsultantMatch(
                investor_id=investor_id,
                consultant_id=consultant_uuid,
                project_id=project_id,
                score=float(item.get("score", 0.0)),
                explanation=item.get("explanation"),
            )
        )
        created += 1
    await db.flush()
    return created
