"""Public contact form (PRD §6.1 Contact page)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field

from app.core.rate_limit import RateTier, rate_limit
from app.schemas.common import MessageResponse
from app.services import email as email_service

router = APIRouter(tags=["contact"])


class ContactForm(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    company: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=5000)


@router.post(
    "/contact",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit(RateTier.auth))],
)
async def submit_contact(form: ContactForm) -> MessageResponse:
    await email_service.send_contact_form(
        name=form.name,
        email=form.email,
        message=form.message,
        company=form.company,
        subject=form.subject,
    )
    return MessageResponse(message="Thank you — we'll be in touch shortly.")
