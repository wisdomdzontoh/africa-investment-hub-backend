"""Due-diligence service (PRD §6.8).

One ``DueDiligenceRequest`` per match, carrying a JSONB checklist. Investor and
facilitator upload evidence per item; an admin signs items off. The request
status is derived from item progress.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.due_diligence import DueDiligenceRequest
from app.models.enums import DueDiligenceStatus
from app.models.match import Match

# Default DD checklist seeded on request (admins refine per deal later).
_DEFAULT_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("Legal", "Certificate of incorporation"),
    ("Legal", "Material contracts & agreements"),
    ("Legal", "Litigation & compliance history"),
    ("Financial", "Audited financial statements"),
    ("Financial", "Management accounts (last 12 months)"),
    ("Financial", "Tax compliance certificate"),
    ("Operational", "Detailed business plan"),
    ("Operational", "Key team CVs"),
    ("ESG", "Environmental & social impact assessment"),
)


def _seed_checklist() -> list[dict]:
    return [
        {
            "item_id": str(uuid.uuid4()),
            "category": category,
            "title": title,
            "status": "pending",
            "document_r2_key": None,
            "filename": None,
        }
        for category, title in _DEFAULT_CHECKLIST
    ]


def _derive_status(checklist: list[dict]) -> DueDiligenceStatus:
    statuses = [item.get("status", "pending") for item in checklist]
    if checklist and all(s == "approved" for s in statuses):
        return DueDiligenceStatus.completed
    if any(s in {"submitted", "approved", "rejected"} for s in statuses):
        return DueDiligenceStatus.in_progress
    return DueDiligenceStatus.requested


async def get_for_match(
    db: AsyncSession, match_id: uuid.UUID
) -> DueDiligenceRequest | None:
    result = await db.execute(
        select(DueDiligenceRequest).where(DueDiligenceRequest.match_id == match_id)
    )
    return result.scalar_one_or_none()


async def get_or_404(db: AsyncSession, dd_id: uuid.UUID) -> DueDiligenceRequest:
    dd = await db.get(DueDiligenceRequest, dd_id)
    if dd is None:
        raise NotFoundError("Due-diligence request not found.")
    return dd


async def create_for_match(db: AsyncSession, *, match: Match) -> DueDiligenceRequest:
    existing = await get_for_match(db, match.id)
    if existing is not None:
        raise ConflictError("Due diligence has already been requested for this match.")
    dd = DueDiligenceRequest(
        match_id=match.id,
        checklist=_seed_checklist(),
        status=DueDiligenceStatus.requested,
    )
    db.add(dd)
    await db.flush()
    return dd


def _find_item(dd: DueDiligenceRequest, item_id: str) -> dict:
    for item in dd.checklist:
        if item.get("item_id") == item_id:
            return item
    raise NotFoundError("Checklist item not found.")


async def set_item_document(
    db: AsyncSession, *, dd: DueDiligenceRequest, item_id: str, r2_key: str, filename: str
) -> DueDiligenceRequest:
    # Reassign the list so SQLAlchemy tracks the JSONB mutation.
    checklist = [dict(item) for item in dd.checklist]
    item = next((i for i in checklist if i.get("item_id") == item_id), None)
    if item is None:
        raise NotFoundError("Checklist item not found.")
    item["document_r2_key"] = r2_key
    item["filename"] = filename
    item["status"] = "submitted"
    dd.checklist = checklist
    dd.status = _derive_status(checklist)
    await db.flush()
    return dd


async def set_item_status(
    db: AsyncSession, *, dd: DueDiligenceRequest, item_id: str, status: str
) -> DueDiligenceRequest:
    checklist = [dict(item) for item in dd.checklist]
    item = next((i for i in checklist if i.get("item_id") == item_id), None)
    if item is None:
        raise NotFoundError("Checklist item not found.")
    item["status"] = status
    if status == "approved":
        item["signed_off_at"] = datetime.now(UTC).isoformat()
    dd.checklist = checklist
    dd.status = _derive_status(checklist)
    await db.flush()
    return dd
