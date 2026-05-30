"""OpenAI access layer (PRD §12, §8.4).

Centralises model tiering (gpt-4o-mini for cheap/FAQ, gpt-4o for complex),
Langfuse tracing, and Redis response caching. All chat/embedding calls in the
codebase go through here so cost controls are applied uniformly.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)


@lru_cache
def _openai() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


@lru_cache
def _langfuse() -> Any | None:
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST or None,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to initialise Langfuse; tracing disabled")
        return None


def pick_model(*, complex_query: bool) -> str:
    """Model tiering (PRD §12.1 cost management)."""
    return settings.OPENAI_CHAT_MODEL if complex_query else settings.OPENAI_CHAT_MODEL_CHEAP


def _cache_key(prefix: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"ai:cache:{prefix}:{digest}"


async def embed(text: str) -> list[float]:
    """Embed a single string with text-embedding-3-small."""
    resp = await _openai().embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL, input=text
    )
    return resp.data[0].embedding


async def chat_completion(
    *,
    messages: list[dict[str, str]],
    complex_query: bool,
    cache_key: str | None = None,
    trace_name: str = "chat",
    json_mode: bool = False,
) -> str:
    """Non-streaming completion with optional Redis caching + Langfuse trace."""
    redis = get_redis()
    model = pick_model(complex_query=complex_query)

    if cache_key:
        key = _cache_key(trace_name, cache_key)
        cached = await redis.get(key)
        if cached:
            return cached

    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    lf = _langfuse()
    trace = lf.trace(name=trace_name) if lf else None
    resp = await _openai().chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    if trace is not None:
        trace.generation(
            name=trace_name,
            model=model,
            input=messages,
            output=content,
            usage={
                "input": resp.usage.prompt_tokens if resp.usage else None,
                "output": resp.usage.completion_tokens if resp.usage else None,
            },
        )

    if cache_key:
        await redis.set(
            _cache_key(trace_name, cache_key),
            content,
            ex=settings.AI_RESPONSE_CACHE_TTL_SECONDS,
        )
    return content


async def chat_stream(
    *, messages: list[dict[str, str]], complex_query: bool, trace_name: str = "chat"
) -> AsyncIterator[str]:
    """Stream a completion token-by-token (for SSE)."""
    model = pick_model(complex_query=complex_query)
    lf = _langfuse()
    trace = lf.trace(name=trace_name) if lf else None
    collected: list[str] = []

    stream = await _openai().chat.completions.create(
        model=model, messages=messages, stream=True
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            collected.append(delta)
            yield delta

    if trace is not None:
        trace.generation(
            name=trace_name, model=model, input=messages, output="".join(collected)
        )


def structured_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse structured JSON from model output")
        return {}
