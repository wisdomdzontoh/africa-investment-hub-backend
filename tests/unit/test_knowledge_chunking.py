"""Unit tests for RAG text chunking."""

from __future__ import annotations

from app.services.knowledge_service import _CHUNK_WORDS, _OVERLAP_WORDS, chunk_text


def test_empty_text() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_text_single_chunk() -> None:
    chunks = chunk_text("a short sentence")
    assert chunks == ["a short sentence"]


def test_long_text_overlaps() -> None:
    words = [f"w{i}" for i in range(_CHUNK_WORDS * 2)]
    chunks = chunk_text(" ".join(words))
    assert len(chunks) >= 2
    # Consecutive chunks share the overlap window.
    first_tail = chunks[0].split()[-_OVERLAP_WORDS:]
    second_head = chunks[1].split()[:_OVERLAP_WORDS]
    assert first_tail == second_head
