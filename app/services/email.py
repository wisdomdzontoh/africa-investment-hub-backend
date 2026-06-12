"""Transactional email via Resend (PRD §6.2, §16).

Phase 1 sends locale-aware status emails (registration received, approved,
rejected, info requested) and routes contact-form submissions to the admin
inbox. Templates are simple server-rendered HTML here; richer React Email
templates are introduced in Phase 3 with full localisation.

Sending is best-effort and typically invoked from an ARQ task so a transient
provider error never blocks the request path.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import Locale

logger = get_logger(__name__)


# Minimal en/fr/zh subject + body lines. Phase 3 replaces with full templates.
_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "registration_received": {
        "en": {
            "subject": "We've received your registration",
            "body": "Thank you for registering. Our team will review your submission "
            "and update you within 72 hours.",
        }
    },
    "status_approved": {
        "en": {
            "subject": "Your account has been approved",
            "body": "Good news — your account is approved. You now have full access "
            "to the platform.",
        }
    },
    "status_rejected": {
        "en": {
            "subject": "Update on your registration",
            "body": "Unfortunately we could not approve your submission at this time. "
            "Reason: {reason}",
        }
    },
    "status_request_info": {
        "en": {
            "subject": "We need a bit more information",
            "body": "To continue reviewing your submission, please provide: {reason}",
        }
    },
    "project_status": {
        "en": {
            "subject": "Update on your project submission",
            "body": "Your project '{title}' status is now: {status}. {reason}",
        }
    },
}


def _render(template: str, locale: Locale, **kwargs: str) -> tuple[str, str]:
    variants = _TEMPLATES.get(template, {})
    chosen = variants.get(locale.value) or variants.get(Locale.en.value)
    if not chosen:
        return ("Notification", "")
    subject = chosen["subject"].format(**kwargs)
    body = chosen["body"].format(**{k: v or "" for k, v in kwargs.items()})
    return subject, body


async def send_email(
    *, to: str, subject: str, html: str, reply_to: str | None = None
) -> None:
    """Send a raw email through Resend. No-op (logged) when unconfigured."""
    if not settings.RESEND_API_KEY:
        logger.warning("Resend not configured; skipping email to %s (%s)", to, subject)
        return

    import resend

    resend.api_key = settings.RESEND_API_KEY
    params: dict[str, object] = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        params["reply_to"] = reply_to
    try:
        resend.Emails.send(params)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - email must not break the caller
        logger.exception("Failed to send email to %s", to)


async def send_template(
    *, to: str, template: str, locale: Locale = Locale.en, **kwargs: str
) -> None:
    subject, body = _render(template, locale, **kwargs)
    html = f"<div style='font-family:sans-serif'><p>{body}</p></div>"
    await send_email(to=to, subject=subject, html=html)


async def send_contact_form(
    *,
    name: str,
    email: str,
    message: str,
    company: str | None = None,
    subject: str | None = None,
) -> None:
    """Route a public contact-form submission to the admin inbox (PRD §6.1).

    All fields are attacker-controlled — escape before embedding in HTML.
    """
    from html import escape

    parts = [f"<p><strong>From:</strong> {escape(name)} &lt;{escape(email)}&gt;</p>"]
    if company:
        parts.append(f"<p><strong>Company:</strong> {escape(company)}</p>")
    if subject:
        parts.append(f"<p><strong>Subject:</strong> {escape(subject)}</p>")
    parts.append(f"<p><strong>Message:</strong></p><p>{escape(message)}</p>")
    await send_email(
        to=settings.EMAIL_ADMIN_INBOX,
        subject=f"Contact form: {subject or name}",
        html="".join(parts),
        reply_to=email,
    )
