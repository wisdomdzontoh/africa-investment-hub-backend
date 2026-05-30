"""AI risk assessment (PRD §12.5) — advisory only.

Produces a structured risk breakdown for a project and stores it on the
project's ``admin_notes`` for the admin to review. The admin sets the final
risk level; the AI suggestion is never auto-applied.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config_text import RISK_ASSESSMENT_PROMPT
from app.models.project import Project
from app.services.ai import client


async def assess(db: AsyncSession, project_id: uuid.UUID) -> dict:
    project = await db.get(Project, project_id)
    if project is None:
        return {}

    summary = (
        f"Country: {project.country}\nSector: {project.sector}\n"
        f"Stage: {project.project_stage.value}\nFunding: {project.funding_required}\n"
        f"Description: {project.brief_description}\n{project.executive_summary or ''}"
    )
    content = await client.chat_completion(
        messages=[
            {"role": "system", "content": RISK_ASSESSMENT_PROMPT},
            {"role": "user", "content": summary},
        ],
        complex_query=True,
        trace_name="risk_assessment",
        json_mode=True,
    )
    assessment = client.structured_json(content)
    if assessment:
        note = "AI risk assessment (advisory):\n" + json.dumps(assessment, indent=2)
        existing = project.admin_notes or ""
        project.admin_notes = f"{existing}\n\n{note}".strip()
        await db.flush()
    return assessment
