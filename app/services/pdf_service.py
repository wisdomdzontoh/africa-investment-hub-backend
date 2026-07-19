"""Deal-document PDF generation (PRD §6.10) — NDA and MOU.

Rendered on the fly with WeasyPrint from HTML templates; nothing is persisted.
The documents are platform-generated templates that capture the parties and
deal context — they are not a substitute for independent legal review.
"""

from __future__ import annotations

from datetime import date
from html import escape

from app.models.investor import InvestorProfile
from app.models.project import Project

_PLATFORM = "African Investment Hub"

_BASE_CSS = """
  @page { size: A4; margin: 2.2cm; }
  body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; font-size: 11pt; line-height: 1.6; }
  h1 { font-size: 18pt; margin: 0 0 4pt; }
  .eyebrow { font-family: monospace; font-size: 8pt; letter-spacing: 0.12em; text-transform: uppercase; color: #c0392b; }
  .meta { margin: 16pt 0; border: 1px solid #e5ded7; border-radius: 6px; padding: 12pt 14pt; background: #fdf6f0; }
  .meta dt { font-size: 8pt; text-transform: uppercase; letter-spacing: 0.06em; color: #6b6b6b; }
  .meta dd { margin: 0 0 8pt; font-weight: 600; }
  h2 { font-size: 11pt; margin: 18pt 0 4pt; }
  ol { padding-left: 16pt; }
  li { margin-bottom: 8pt; }
  .sign { margin-top: 28pt; display: flex; justify-content: space-between; gap: 24pt; }
  .sign div { flex: 1; border-top: 1px solid #1a1a1a; padding-top: 6pt; font-size: 9pt; color: #6b6b6b; }
  .footer { margin-top: 24pt; font-size: 8pt; color: #8a8a8a; }
"""


def _meta_row(label: str, value: str) -> str:
    return f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>"


def _render(html_body: str) -> bytes:
    # Imported lazily — WeasyPrint pulls in native libs and is slow to import.
    from weasyprint import HTML

    document = f"<html><head><style>{_BASE_CSS}</style></head><body>{html_body}</body></html>"
    return HTML(string=document).write_pdf()  # type: ignore[no-any-return]


def _meta_block(project: Project, investor: InvestorProfile) -> str:
    return (
        '<dl class="meta">'
        + _meta_row("Disclosing party", f"{project.title} (facilitated via {_PLATFORM})")
        + _meta_row("Receiving party", investor.company_name)
        + _meta_row("Project sector / country", f"{project.sector} · {project.country}")
        + _meta_row("Date", date.today().isoformat())
        + "</dl>"
    )


def render_nda(*, project: Project, investor: InvestorProfile) -> bytes:
    body = (
        '<p class="eyebrow">Confidential</p>'
        "<h1>Non-Disclosure Agreement</h1>"
        f"<p>This agreement governs confidential information shared via {escape(_PLATFORM)} "
        "between the parties below in connection with a potential investment.</p>"
        + _meta_block(project, investor)
        + "<h2>1. Confidential information</h2><ol>"
        "<li>The receiving party will treat all non-public project information — financials, "
        "documents, and the disclosing party's identity where applicable — as strictly confidential.</li>"
        "<li>Confidential information may be used solely to evaluate the potential investment and "
        "for no other purpose.</li>"
        "<li>Confidential information will not be disclosed to third parties without prior written "
        "consent, save for advisors bound by equivalent obligations.</li>"
        "<li>These obligations survive for three (3) years from the date of disclosure.</li>"
        "</ol>"
        '<div class="sign"><div>Receiving party — signature &amp; date</div>'
        "<div>Authorised platform representative</div></div>"
        '<p class="footer">Platform-generated template. Not a substitute for independent legal '
        "advice. Electronic acknowledgement on-platform constitutes acceptance.</p>"
    )
    return _render(body)


def render_mou(*, project: Project, investor: InvestorProfile) -> bytes:
    body = (
        '<p class="eyebrow">Draft for discussion</p>'
        "<h1>Memorandum of Understanding</h1>"
        f"<p>This memorandum records the parties' intent to progress discussions regarding an "
        f"investment in the project below, facilitated via {escape(_PLATFORM)}.</p>"
        + _meta_block(project, investor)
        + "<h2>1. Purpose</h2><ol>"
        "<li>The parties intend to negotiate, in good faith, the terms of a potential investment.</li>"
        "<li>This memorandum is non-binding except for the confidentiality and exclusivity clauses.</li>"
        "<li>Each party bears its own costs during the evaluation and negotiation period.</li>"
        "<li>Definitive terms are subject to satisfactory due diligence and binding agreements.</li>"
        "</ol>"
        '<div class="sign"><div>Receiving party — signature &amp; date</div>'
        "<div>Disclosing party — signature &amp; date</div></div>"
        '<p class="footer">Platform-generated draft. Non-binding. Subject to due diligence and '
        "definitive documentation reviewed by each party's legal counsel.</p>"
    )
    return _render(body)
