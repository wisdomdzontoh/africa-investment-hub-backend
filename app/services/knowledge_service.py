"""Knowledge base maintenance for RAG (PRD §12.1).

Turns published country content into embedded ``knowledge_chunks``. Chunking is
~512 tokens with ~50-token overlap, approximated by words (1 token ≈ 0.75
words). Re-indexing replaces the chunks for a given source so updates don't
leave stale content.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import localize
from app.models.country import CountryContent
from app.models.enums import KnowledgeContentType, Locale
from app.models.knowledge import KnowledgeChunk
from app.services.ai import client

_CHUNK_WORDS = 380  # ≈ 512 tokens
_OVERLAP_WORDS = 40  # ≈ 50 tokens

_COUNTRY_SECTIONS = (
    "investment_climate",
    "investment_laws",
    "tax_system",
    "business_registration",
    "licensing_requirements",
    "foreign_ownership_rules",
    "repatriation_policy",
    "immigration_requirements",
)


def chunk_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    step = _CHUNK_WORDS - _OVERLAP_WORDS
    while start < len(words):
        chunk = words[start : start + _CHUNK_WORDS]
        chunks.append(" ".join(chunk))
        start += step
    return chunks


async def reindex_country_content(db: AsyncSession, country_code: str) -> int:
    """Re-embed all sections of one country. Returns the chunk count written."""
    code = country_code.upper()
    result = await db.execute(
        select(CountryContent).where(CountryContent.country_code == code)
    )
    country = result.scalar_one_or_none()
    if country is None or not country.is_published:
        return 0

    # Drop existing chunks for this source.
    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.source_type == "country_content",
            KnowledgeChunk.source_id == country.id,
        )
    )

    written = 0
    for section in _COUNTRY_SECTIONS:
        # Index the English variant (locale-agnostic retrieval — PRD §7).
        text = localize(getattr(country, section), Locale.en)
        if not text:
            continue
        for piece in chunk_text(str(text)):
            embedding = await client.embed(piece)
            db.add(
                KnowledgeChunk(
                    content_type=KnowledgeContentType.country,
                    source_type="country_content",
                    source_id=country.id,
                    country_code=code,
                    section=section,
                    title=f"{country.country_name} — {section.replace('_', ' ').title()}",
                    content=piece,
                    embedding=embedding,
                )
            )
            written += 1
    await db.flush()
    return written
