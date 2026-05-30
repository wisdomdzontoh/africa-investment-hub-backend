"""Shared Pydantic schema building blocks."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response models read from SQLAlchemy ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """Cursor-paginated envelope (PRD §11)."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class MessageResponse(BaseModel):
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail


class PresignUploadRequest(BaseModel):
    filename: str
    content_type: str
    doc_type: str  # e.g. company_registration, aml_certificate, business_plan


class PresignUploadResponse(BaseModel):
    upload_url: str
    r2_key: str
    expires_in: int
    method: str = "PUT"
