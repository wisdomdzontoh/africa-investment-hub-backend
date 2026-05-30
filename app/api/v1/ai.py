"""AI endpoints (PRD §6.7, §11, §12)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import DbDep, LocaleDep, OptionalUser
from app.core.rate_limit import RateTier, rate_limit
from app.db.session import SessionLocal
from app.schemas.ai import ChatRequest, MatchExplanation
from app.services import match_service
from app.services.ai import chat as chat_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat", dependencies=[Depends(rate_limit(RateTier.ai))])
async def chat(payload: ChatRequest, db: DbDep, user: OptionalUser, locale: LocaleDep) -> StreamingResponse:
    """Stream the assistant's reply as Server-Sent Events (PRD §12.1)."""
    session = await chat_service.get_or_create_session(
        db, session_token=payload.session_token, user_id=user.id if user else None
    )
    # Detach values needed inside the generator; the request session closes
    # once the response starts streaming, so we use a fresh session there.
    session_token = session.session_token
    user_id = user.id if user else None

    async def event_stream() -> AsyncIterator[str]:
        async with SessionLocal() as stream_db:
            s = await chat_service.get_or_create_session(
                stream_db, session_token=session_token, user_id=user_id
            )
            async for token in chat_service.stream_reply(
                stream_db, session=s, message=payload.message, locale=locale
            ):
                yield f"data: {token}\n\n"
            await stream_db.commit()
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/match-explain/{match_id}", response_model=MatchExplanation)
async def match_explain(match_id: uuid.UUID, db: DbDep, _user: OptionalUser) -> MatchExplanation:
    match = await match_service.get_or_404(db, match_id)
    return MatchExplanation(
        match_id=str(match.id),
        explanation=match.explanation or "No explanation available for this match yet.",
    )
