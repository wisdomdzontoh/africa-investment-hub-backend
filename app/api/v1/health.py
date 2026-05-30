"""Health check endpoint (PRD §11): reports app, db, and redis status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import get_redis
from app.db.session import get_db

router = APIRouter(tags=["health"])


async def _check_db(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 - health must never raise
        return "error"


async def _check_redis() -> str:
    try:
        pong = await get_redis().ping()
        return "ok" if pong else "error"
    except Exception:  # noqa: BLE001
        return "error"


@router.get("/health", summary="Service health and dependency status")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    db_status = await _check_db(db)
    redis_status = await _check_redis()
    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "db": db_status,
        "redis": redis_status,
    }
