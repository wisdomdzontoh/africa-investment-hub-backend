"""AI chatbot schemas (PRD §12.1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_token: str = Field(min_length=8, max_length=255)
    message: str = Field(min_length=1, max_length=4000)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    timestamp: str | None = None


class ChatSessionOut(BaseModel):
    session_token: str
    messages: list[ChatMessage]


class MatchExplanation(BaseModel):
    match_id: str
    explanation: str
