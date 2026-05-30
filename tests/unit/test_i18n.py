"""Unit tests for i18n locale parsing and JSONB localisation."""

from __future__ import annotations

import pytest

from app.core.i18n import localize, parse_accept_language
from app.models.enums import Locale


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, Locale.en),
        ("", Locale.en),
        ("fr", Locale.fr),
        ("zh-CN,zh;q=0.9", Locale.zh),
        ("de,fr;q=0.8,en;q=0.5", Locale.fr),
        ("es-ES", Locale.en),  # unsupported → default
        ("en-US,en;q=0.9", Locale.en),
    ],
)
def test_parse_accept_language(header: str | None, expected: Locale) -> None:
    assert parse_accept_language(header) == expected


def test_localize_requested_locale() -> None:
    value = {"en": "Hello", "fr": "Bonjour", "zh": "你好"}
    assert localize(value, Locale.fr) == "Bonjour"
    assert localize(value, Locale.zh) == "你好"


def test_localize_falls_back_to_english() -> None:
    value = {"en": "Hello"}
    assert localize(value, Locale.fr) == "Hello"


def test_localize_falls_back_to_any_when_no_english() -> None:
    value = {"fr": "Bonjour"}
    assert localize(value, Locale.zh) == "Bonjour"


def test_localize_passthrough_non_dict() -> None:
    assert localize("plain", Locale.en) == "plain"
    assert localize(None, Locale.en) is None
