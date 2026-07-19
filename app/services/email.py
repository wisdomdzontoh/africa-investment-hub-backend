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


# Localised subject + body lines per template (en/fr/zh — PRD §7 i18n).
# Phase 3 replaces these with full React Email templates.
_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "registration_received": {
        "en": {
            "subject": "We've received your registration",
            "body": "Thank you for registering. Our team will review your submission "
            "and update you within 72 hours.",
        },
        "fr": {
            "subject": "Nous avons bien reçu votre inscription",
            "body": "Merci pour votre inscription. Notre équipe examinera votre dossier "
            "et vous tiendra informé sous 72 heures.",
        },
        "zh": {
            "subject": "我们已收到您的注册申请",
            "body": "感谢您的注册。我们的团队将审核您提交的资料，并在72小时内向您反馈。",  # noqa: RUF001
        },
    },
    "status_approved": {
        "en": {
            "subject": "Your account has been approved",
            "body": "Good news — your account is approved. You now have full access "
            "to the platform.",
        },
        "fr": {
            "subject": "Votre compte a été approuvé",
            "body": "Bonne nouvelle — votre compte est approuvé. Vous avez désormais "
            "un accès complet à la plateforme.",
        },
        "zh": {
            "subject": "您的账户已获批准",
            "body": "好消息——您的账户已获批准。您现在可以使用平台的全部功能。",
        },
    },
    "status_rejected": {
        "en": {
            "subject": "Update on your registration",
            "body": "Unfortunately we could not approve your submission at this time. "
            "Reason: {reason}",
        },
        "fr": {
            "subject": "Mise à jour concernant votre inscription",
            "body": "Malheureusement, nous n'avons pas pu approuver votre dossier pour "
            "le moment. Motif : {reason}",
        },
        "zh": {
            "subject": "您的注册申请进展",
            "body": "很遗憾，我们目前无法批准您提交的申请。原因：{reason}",  # noqa: RUF001
        },
    },
    "status_request_info": {
        "en": {
            "subject": "We need a bit more information",
            "body": "To continue reviewing your submission, please provide: {reason}",
        },
        "fr": {
            "subject": "Nous avons besoin d'informations complémentaires",
            "body": "Pour poursuivre l'examen de votre dossier, veuillez fournir : {reason}",
        },
        "zh": {
            "subject": "我们需要更多信息",
            "body": "为了继续审核您提交的申请，请提供：{reason}",  # noqa: RUF001
        },
    },
    "project_interest": {
        "en": {
            "subject": "An investor is interested in your project",
            "body": "An investor has expressed interest in '{title}'. Our team will "
            "coordinate the next steps and follow up with you shortly.",
        },
        "fr": {
            "subject": "Un investisseur s'intéresse à votre projet",
            "body": "Un investisseur a manifesté son intérêt pour « {title} ». Notre "
            "équipe coordonnera les prochaines étapes et reviendra vers vous rapidement.",
        },
        "zh": {
            "subject": "有投资者对您的项目感兴趣",
            "body": "有投资者对“{title}”表示了兴趣。我们的团队将协调后续步骤并尽快与您联系。",  # noqa: RUF001
        },
    },
    "project_status": {
        "en": {
            "subject": "Update on your project submission",
            "body": "Your project '{title}' status is now: {status}. {reason}",
        },
        "fr": {
            "subject": "Mise à jour de votre projet",
            "body": "Le statut de votre projet « {title} » est désormais : {status}. {reason}",
        },
        "zh": {
            "subject": "您的项目提交进展",
            "body": "您的项目“{title}”当前状态为：{status}。{reason}",  # noqa: RUF001
        },
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

    import asyncio

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
        # The Resend SDK is synchronous — run it off the event loop so a slow
        # provider response never stalls other in-flight requests.
        await asyncio.to_thread(resend.Emails.send, params)  # type: ignore[arg-type]
    except Exception:
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
