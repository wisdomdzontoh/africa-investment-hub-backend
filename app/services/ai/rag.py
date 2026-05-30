"""RAG retrieval over the knowledge base (PRD §12.1).

Embeds the query, runs a pgvector cosine-similarity search over
``knowledge_chunks``, and returns the top-K chunks with scores. The caller
uses the top score to decide whether to escalate to a human advisor.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk
from app.services.ai import client


@dataclass(slots=True)
class RetrievedChunk:
    content: str
    title: str | None
    score: float
    country_code: str | None


async def retrieve(
    db: AsyncSession, *, query: str, k: int = 5
) -> list[RetrievedChunk]:
    """Return the top-K most relevant knowledge chunks for ``query``.

    Score is cosine similarity (1 - cosine distance), in [0, 1].
    """
    query_embedding = await client.embed(query)
    distance = KnowledgeChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            KnowledgeChunk.content,
            KnowledgeChunk.title,
            KnowledgeChunk.country_code,
            (1 - distance).label("score"),
        )
        .where(KnowledgeChunk.embedding.is_not(None))
        .order_by(distance.asc())
        .limit(k)
    )
    result = await db.execute(stmt)
    return [
        RetrievedChunk(content=row.content, title=row.title, score=float(row.score), country_code=row.country_code)
        for row in result.all()
    ]


def top_score(chunks: list[RetrievedChunk]) -> float:
    return max((c.score for c in chunks), default=0.0)
