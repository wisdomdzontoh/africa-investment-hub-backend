"""ARQ background tasks (PRD §8.2, §12).

Each task opens its own DB session (workers run outside the request lifecycle).
Tasks are registered on ``WorkerSettings.functions`` in ``worker.py``; the
function ``__name__`` is the job name used by ``enqueue(...)``.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.ai import embeddings, matching, risk
from app.services.knowledge_service import reindex_country_content

logger = get_logger(__name__)


async def embed_profile(ctx: dict[str, Any], investor_id: str) -> None:
    async with SessionLocal() as db:
        await embeddings.embed_investor(db, investor_id)  # type: ignore[arg-type]
        await db.commit()


async def embed_project(ctx: dict[str, Any], project_id: str) -> None:
    async with SessionLocal() as db:
        await embeddings.embed_project(db, project_id)  # type: ignore[arg-type]
        await db.commit()


async def embed_consultant(ctx: dict[str, Any], consultant_id: str) -> None:
    async with SessionLocal() as db:
        await embeddings.embed_consultant(db, consultant_id)  # type: ignore[arg-type]
        await db.commit()


async def generate_matches(ctx: dict[str, Any], investor_id: str) -> int:
    import uuid

    async with SessionLocal() as db:
        count = await matching.generate_project_matches(db, uuid.UUID(investor_id))
        await db.commit()
        logger.info("Generated %d matches for investor %s", count, investor_id)
        return count


async def generate_consultant_matches(
    ctx: dict[str, Any], investor_id: str, project_id: str | None = None
) -> int:
    import uuid

    async with SessionLocal() as db:
        count = await matching.generate_consultant_matches(
            db,
            investor_id=uuid.UUID(investor_id),
            project_id=uuid.UUID(project_id) if project_id else None,
        )
        await db.commit()
        return count


async def assess_project_risk(ctx: dict[str, Any], project_id: str) -> None:
    import uuid

    async with SessionLocal() as db:
        await risk.assess(db, uuid.UUID(project_id))
        await db.commit()


async def reindex_country(ctx: dict[str, Any], country_code: str) -> int:
    async with SessionLocal() as db:
        count = await reindex_country_content(db, country_code)
        await db.commit()
        return count


async def send_templated_email(
    ctx: dict[str, Any], *, to: str, template: str, locale: str = "en", **kwargs: str
) -> None:
    """Send a localised transactional email off the request path (PRD §6.2)."""
    from app.models.enums import Locale
    from app.services import email as email_service

    try:
        resolved = Locale(locale)
    except ValueError:
        resolved = Locale.en
    await email_service.send_template(to=to, template=template, locale=resolved, **kwargs)


async def notify_matching_investors(ctx: dict[str, Any], project_id: str) -> int:
    """Alert approved investors whose focus overlaps a newly approved project
    (PRD §6.5 notifications). Rule-based (sector or country overlap) so it
    works deterministically alongside the AI matching pipeline."""
    import uuid

    from sqlalchemy import or_, select

    from app.models.enums import ProjectStatus, UserRole, UserStatus
    from app.models.investor import InvestorProfile
    from app.models.project import Project
    from app.models.user import User
    from app.services import notification_service

    notified = 0
    async with SessionLocal() as db:
        project = await db.get(Project, uuid.UUID(project_id))
        if project is None or project.status != ProjectStatus.approved:
            return 0

        stmt = (
            select(InvestorProfile, User)
            .join(User, User.id == InvestorProfile.user_id)
            .where(
                User.role == UserRole.investor,
                User.status == UserStatus.approved,
                User.deleted_at.is_(None),
                or_(
                    InvestorProfile.investment_sectors.any(project.sector),
                    InvestorProfile.investment_countries.any(project.country),
                ),
            )
        )
        for _profile, user in (await db.execute(stmt)).all():
            await notification_service.create(
                db,
                user_id=user.id,
                type="new_project",
                title="A new opportunity matches your focus",
                body=project.title,
                link=f"/opportunities/{project.id}",
            )
            notified += 1
        await db.commit()

    logger.info("Notified %d investors about project %s", notified, project_id)
    return notified


def _document_keys(*document_lists: object) -> list[str]:
    """Collect R2 keys from ``documents`` JSONB lists ([{type, r2_key, ...}])."""
    keys: list[str] = []
    for documents in document_lists:
        if not isinstance(documents, list):
            continue
        for doc in documents:
            if isinstance(doc, dict) and doc.get("r2_key"):
                keys.append(str(doc["r2_key"]))
    return keys


async def purge_deleted_users(ctx: dict[str, Any]) -> int:
    """Hard-delete users soft-deleted more than 30 days ago (PRD §14, cron).

    Per user: confirm the Clerk identity is gone, remove their R2 documents,
    then delete the row — profiles, projects, matches, and notifications
    cascade at the DB level; audit rows survive with the actor nulled."""
    import asyncio

    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core import clerk_client
    from app.models.user import User
    from app.services import storage, user_service

    purged = 0
    async with SessionLocal() as db:
        expired = await user_service.list_soft_deleted(db, older_than_days=30)
        for user in expired:
            user_id = user.id
            # Re-drive the Clerk deletion; 404 (already gone) counts as done.
            if not await clerk_client.delete_user(user.clerk_id):
                logger.warning("Purge deferred for %s — Clerk deletion pending", user_id)
                continue

            loaded = (
                await db.execute(
                    select(User)
                    .where(User.id == user_id)
                    .options(
                        selectinload(User.investor_profile),
                        selectinload(User.consultant_profile),
                        selectinload(User.projects),
                    )
                )
            ).scalar_one()
            keys = _document_keys(
                loaded.investor_profile.documents if loaded.investor_profile else None,
                loaded.consultant_profile.documents if loaded.consultant_profile else None,
                *[p.documents for p in loaded.projects],
            )
            for key in keys:
                try:
                    await asyncio.to_thread(storage.delete_object, key)
                except Exception:
                    logger.exception("Failed to delete R2 object %s", key)

            # Core DELETE — children are removed by DB-level ON DELETE CASCADE
            # (audit/chat rows survive with the user reference nulled), which
            # avoids ORM cascade lazy-loads that async sessions cannot perform.
            await db.execute(sa_delete(User).where(User.id == user_id))
            await db.commit()
            purged += 1
            logger.info("Purged user %s (%d documents removed)", user_id, len(keys))
    return purged


async def reconcile_clerk_users(ctx: dict[str, Any]) -> dict[str, int]:
    """Nightly Clerk↔DB convergence sweep (cron).

    Direction 1 (DB→Clerk): any locally deleted user still present in Clerk is
    deleted there — retries deletions that failed inline.
    Direction 2 (Clerk→DB): every Clerk user is upserted locally, catching
    webhooks that were dropped. Locally deleted users are never resurrected."""
    from contextlib import suppress

    from app.core import clerk_client
    from app.models.enums import UserRole
    from app.services import user_service

    deleted_in_clerk = 0
    upserted = 0

    async with SessionLocal() as db:
        # Direction 1 — propagate local deletions.
        for user in await user_service.list_soft_deleted(db):
            if await clerk_client.delete_user(user.clerk_id):
                deleted_in_clerk += 1

        # Direction 2 — ensure every Clerk user exists locally.
        offset = 0
        page_size = 100
        while True:
            page = await clerk_client.list_users(limit=page_size, offset=offset)
            if not page:
                break
            for data in page:
                clerk_id = data.get("id")
                if not clerk_id:
                    continue
                existing = await user_service.get_by_clerk_id(db, clerk_id)
                if existing is not None and existing.deleted_at is not None:
                    continue  # pending purge — do not resurrect
                emails = data.get("email_addresses") or []
                primary_id = data.get("primary_email_address_id")
                email = next(
                    (e.get("email_address") for e in emails if e.get("id") == primary_id),
                    emails[0].get("email_address") if emails else None,
                )
                role = None
                meta = data.get("public_metadata") or {}
                if isinstance(meta, dict) and meta.get("role"):
                    with suppress(ValueError):
                        role = UserRole(meta["role"])
                await user_service.upsert_from_webhook(
                    db, clerk_id=clerk_id, email=email, role=role
                )
                upserted += 1
            if len(page) < page_size:
                break
            offset += page_size
        await db.commit()

    logger.info(
        "Clerk reconciliation: %d deletions propagated, %d users upserted",
        deleted_in_clerk,
        upserted,
    )
    return {"deleted_in_clerk": deleted_in_clerk, "upserted": upserted}
