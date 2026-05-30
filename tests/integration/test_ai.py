"""AI layer — embeddings, RAG retrieval, matching, risk, chat escalation.

OpenAI calls are stubbed; the pgvector SQL paths run for real against the test
database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models.consultant import ConsultantProfile
from app.models.enums import (
    ConsultantStatus,
    FundingType,
    KnowledgeContentType,
    MatchStatus,
    ProjectStage,
    ProjectStatus,
    UserRole,
)
from app.models.investor import InvestorProfile
from app.models.knowledge import KnowledgeChunk
from app.models.match import Match
from app.models.project import Project
from app.models.user import User
from app.services.ai import chat as chat_service
from app.services.ai import embeddings, matching, rag, risk

pytestmark = pytest.mark.integration


def _vec(primary: int = 0) -> list[float]:
    v = [0.0] * 1536
    v[primary] = 1.0
    return v


def _fake_embed(primary: int = 0):
    """Async stub matching ``client.embed`` (the code awaits it)."""

    async def _embed(text: str) -> list[float]:
        return _vec(primary)

    return _embed


async def _user(db, role=UserRole.investor) -> User:
    u = User(clerk_id=f"c_{uuid.uuid4().hex}", role=role)
    db.add(u)
    await db.flush()
    return u


async def test_embed_investor_sets_vector(db, monkeypatch) -> None:
    monkeypatch.setattr("app.services.ai.client.embed", _fake_embed(3))
    u = await _user(db)
    profile = InvestorProfile(user_id=u.id, company_name="C", country_of_registration="GH")
    db.add(profile)
    await db.commit()

    await embeddings.embed_investor(db, profile.id)
    await db.refresh(profile)
    assert profile.embedding is not None
    assert len(profile.embedding) == 1536


async def test_rag_retrieve_orders_by_similarity(db, monkeypatch) -> None:
    monkeypatch.setattr("app.services.ai.client.embed", _fake_embed(0))
    near = KnowledgeChunk(
        content_type=KnowledgeContentType.faq, content="near", embedding=_vec(0), title="near"
    )
    far = KnowledgeChunk(
        content_type=KnowledgeContentType.faq, content="far", embedding=_vec(5), title="far"
    )
    db.add_all([near, far])
    await db.commit()

    results = await rag.retrieve(db, query="anything", k=2)
    assert results[0].title == "near"
    assert results[0].score > results[1].score


async def test_generate_project_matches(db, monkeypatch) -> None:
    owner = await _user(db, role=UserRole.project_owner)
    project = Project(
        owner_user_id=owner.id,
        title="Solar",
        sector="Renewable Energy",
        country="GH",
        brief_description="d",
        project_stage=ProjectStage.expansion,
        funding_required=Decimal("1000000"),
        funding_type=FundingType.equity,
        status=ProjectStatus.approved,
        embedding=_vec(0),
    )
    db.add(project)
    inv_user = await _user(db)
    investor = InvestorProfile(
        user_id=inv_user.id, company_name="C", country_of_registration="US", embedding=_vec(0)
    )
    db.add(investor)
    await db.commit()

    monkeypatch.setattr("app.services.ai.client.embed", _fake_embed(0))

    async def fake_completion(**kwargs):
        return (
            '{"matches": [{"project_id": "%s", "rank": 1, "score": 0.92, '
            '"explanation": "Strong sector fit."}]}' % project.id
        )

    monkeypatch.setattr("app.services.ai.client.chat_completion", fake_completion)

    created = await matching.generate_project_matches(db, investor.id)
    assert created == 1
    match = (await db.execute(__import__("sqlalchemy").select(Match))).scalar_one()
    assert match.status == MatchStatus.ai_recommended
    assert match.score == pytest.approx(0.92)


async def test_risk_assessment_writes_admin_notes(db, monkeypatch) -> None:
    owner = await _user(db, role=UserRole.project_owner)
    project = Project(
        owner_user_id=owner.id,
        title="Mine",
        sector="Mining",
        country="ZA",
        brief_description="d",
        project_stage=ProjectStage.concept,
        funding_required=Decimal("5000000"),
        funding_type=FundingType.equity,
        status=ProjectStatus.approved,
    )
    db.add(project)
    await db.commit()

    async def fake_completion(**kwargs):
        return '{"overall_risk_score": 6.2, "risk_level_suggestion": "medium"}'

    monkeypatch.setattr("app.services.ai.client.chat_completion", fake_completion)
    result = await risk.assess(db, project.id)
    assert result["risk_level_suggestion"] == "medium"
    await db.refresh(project)
    assert "AI risk assessment" in (project.admin_notes or "")


async def test_chat_escalates_on_low_relevance(db, monkeypatch) -> None:
    # No knowledge chunks → top score 0 → escalation.
    monkeypatch.setattr("app.services.ai.client.embed", _fake_embed(0))
    session = await chat_service.get_or_create_session(
        db, session_token="tok_12345678", user_id=None
    )
    from app.models.enums import Locale

    tokens = []
    async for t in chat_service.stream_reply(
        db, session=session, message="obscure question", locale=Locale.en
    ):
        tokens.append(t)
    assert "".join(tokens) == chat_service.ESCALATION_MESSAGE
    # Exchange persisted.
    assert len(session.messages) == 2


async def test_chat_answers_with_context(db, monkeypatch) -> None:
    monkeypatch.setattr("app.services.ai.client.embed", _fake_embed(0))
    db.add(
        KnowledgeChunk(
            content_type=KnowledgeContentType.country,
            content="Ghana allows 100% foreign ownership.",
            embedding=_vec(0),
            title="Ghana ownership",
        )
    )
    await db.commit()

    async def fake_stream(**kwargs):
        for tok in ["Foreign ", "investors ", "may own 100%."]:
            yield tok

    monkeypatch.setattr("app.services.ai.client.chat_stream", fake_stream)
    from app.models.enums import Locale

    session = await chat_service.get_or_create_session(db, session_token="tok_abcdefgh", user_id=None)
    out = ""
    async for t in chat_service.stream_reply(
        db, session=session, message="ownership in Ghana?", locale=Locale.en
    ):
        out += t
    assert "100%" in out


async def test_reindex_country_creates_chunks(db, monkeypatch) -> None:
    from app.models.country import CountryContent
    from app.services.knowledge_service import reindex_country_content

    monkeypatch.setattr("app.services.ai.client.embed", _fake_embed(1))
    country = CountryContent(
        country_code="GH",
        country_name="Ghana",
        is_published=True,
        foreign_ownership_rules={"en": "Foreigners may own up to 100% of companies. " * 30},
    )
    db.add(country)
    await db.commit()

    count = await reindex_country_content(db, "GH")
    assert count >= 1
    chunks = (
        await db.execute(__import__("sqlalchemy").select(KnowledgeChunk))
    ).scalars().all()
    assert len(chunks) == count
