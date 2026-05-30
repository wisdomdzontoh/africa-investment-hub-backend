"""Unit tests for the NDA-gate status logic (PRD §6.10)."""

from __future__ import annotations

from app.models.enums import (
    NDA_UNLOCKED_STATUSES,
    MatchStatus,
)


def test_locked_before_nda_signed() -> None:
    for status in (
        MatchStatus.ai_recommended,
        MatchStatus.admin_reviewed,
        MatchStatus.investor_notified,
        MatchStatus.investor_interested,
        MatchStatus.nda_sent,
    ):
        assert status not in NDA_UNLOCKED_STATUSES


def test_unlocked_at_and_after_nda_signed() -> None:
    for status in (
        MatchStatus.nda_signed,
        MatchStatus.mou_drafted,
        MatchStatus.mou_signed,
        MatchStatus.in_negotiation,
        MatchStatus.due_diligence,
        MatchStatus.closed_won,
    ):
        assert status in NDA_UNLOCKED_STATUSES


def test_confidential_and_dismissed_do_not_unlock() -> None:
    assert MatchStatus.confidential not in NDA_UNLOCKED_STATUSES
    assert MatchStatus.dismissed not in NDA_UNLOCKED_STATUSES
    assert MatchStatus.closed_lost not in NDA_UNLOCKED_STATUSES
