"""Internationalisation helpers (PRD §7).

A middleware reads the ``Accept-Language`` header and stores the resolved
locale on ``request.state.locale`` (default ``en``). CMS JSONB fields store
``{en, fr, zh}`` variants; ``localize()`` returns the requested locale's value,
falling back to English.
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.models.enums import Locale

DEFAULT_LOCALE = Locale.en
_SUPPORTED = {loc.value for loc in Locale}


def parse_accept_language(header: str | None) -> Locale:
    """Pick the best supported locale from an ``Accept-Language`` header.

    Honours quality weights (``;q=``). Falls back to ``en``.
    """
    if not header:
        return DEFAULT_LOCALE

    ranked: list[tuple[float, str]] = []
    for part in header.split(","):
        token = part.strip()
        if not token:
            continue
        lang, _, q = token.partition(";")
        # Primary subtag only: "fr-FR" -> "fr".
        primary = lang.strip().lower().split("-")[0]
        quality = 1.0
        if q.startswith("q="):
            try:
                quality = float(q[2:])
            except ValueError:
                quality = 0.0
        ranked.append((quality, primary))

    for _, lang in sorted(ranked, key=lambda x: x[0], reverse=True):
        if lang in _SUPPORTED:
            return Locale(lang)
    return DEFAULT_LOCALE


def localize(value: Any, locale: Locale | str, *, fallback: Locale = DEFAULT_LOCALE) -> Any:
    """Extract a single locale's string from a ``{en, fr, zh}`` JSONB value.

    - ``None`` -> ``None``
    - non-dict (already a plain string / list) -> returned unchanged
    - dict -> requested locale, else fallback locale, else first available value
    """
    if value is None or not isinstance(value, dict):
        return value
    loc = locale.value if isinstance(locale, Locale) else str(locale)
    if value.get(loc):
        return value[loc]
    if value.get(fallback.value):
        return value[fallback.value]
    return next((v for v in value.values() if v), None)


class LocaleMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.locale = parse_accept_language(request.headers.get("Accept-Language"))
        return await call_next(request)


def get_request_locale(request: Request) -> Locale:
    return getattr(request.state, "locale", DEFAULT_LOCALE)
