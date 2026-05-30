"""AI Investment Assistant — RAG chat orchestration (PRD §6.7, §12.1).

Retrieves knowledge-base context, builds the prompt (locale-aware, last 8
turns), and streams the answer via SSE. Low-relevance queries are escalated to
a human advisor. Sessions persist in ``chat_sessions`` (anon by token,
logged-in by user_id).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_text import SYSTEM_PROMPT  # local prompt text
from app.core.config import settings
from app.models.chat import ChatSession
from app.models.enums import Locale
from app.services.ai import client, rag

ESCALATION_MESSAGE = (
    "I want to make sure you get accurate guidance on this — let me connect you "
    "with one of our advisors. You can reach them via the Contact page."
)

# Heuristic: queries mentioning these need the stronger model (PRD §12.1).
_COMPLEX_HINTS = (
    "recommend",
    "compare",
    "portfolio",
    "which sector",
    "which country",
    "best",
    "strategy",
    "consultant",
)


def _is_complex(message: str) -> bool:
    lower = message.lower()
    return any(hint in lower for hint in _COMPLEX_HINTS)


async def get_or_create_session(
    db: AsyncSession, *, session_token: str, user_id: uuid.UUID | None
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(ChatSession.session_token == session_token)
    )
    session = result.scalar_one_or_none()
    if session is None:
        session = ChatSession(session_token=session_token, user_id=user_id, messages=[])
        db.add(session)
        await db.flush()
    elif user_id is not None and session.user_id is None:
        session.user_id = user_id
    return session


def _build_messages(
    *, system: str, history: list[dict], context: str, message: str
) -> list[dict[str, str]]:
    recent = history[-(settings.AI_MAX_HISTORY_TURNS * 2) :]
    msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
    if context:
        msgs.append(
            {"role": "system", "content": f"Relevant knowledge base context:\n{context}"}
        )
    for turn in recent:
        msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({"role": "user", "content": message})
    return msgs


async def stream_reply(
    db: AsyncSession,
    *,
    session: ChatSession,
    message: str,
    locale: Locale,
) -> AsyncIterator[str]:
    """Yield answer tokens, then persist the exchange.

    The DB write happens after streaming completes; the route commits the
    session afterwards.
    """
    chunks = await rag.retrieve(db, query=message, k=5)
    score = rag.top_score(chunks)

    now = datetime.now(UTC).isoformat()
    history = list(session.messages)
    full_answer = ""

    if score < settings.RAG_ESCALATION_THRESHOLD:
        # Low confidence — escalate rather than hallucinate (PRD §12.1).
        full_answer = ESCALATION_MESSAGE
        yield ESCALATION_MESSAGE
    else:
        context = "\n\n".join(f"[{c.title or c.country_code or 'doc'}] {c.content}" for c in chunks)
        system = SYSTEM_PROMPT.format(locale=locale.value)
        messages = _build_messages(
            system=system, history=history, context=context, message=message
        )
        async for token in client.chat_stream(
            messages=messages, complex_query=_is_complex(message), trace_name="assistant_chat"
        ):
            full_answer += token
            yield token

    session.messages = [
        *history,
        {"role": "user", "content": message, "timestamp": now},
        {"role": "assistant", "content": full_answer, "timestamp": datetime.now(UTC).isoformat()},
    ]
    await db.flush()
