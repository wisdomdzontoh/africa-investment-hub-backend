"""Aggregates all v1 API routers.

``health`` lives at the root (no /v1 prefix) so external uptime checks hit a
stable path. Everything else is mounted under /v1.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    account,
    ai,
    contact,
    content,
    countries,
    due_diligence,
    health,
    investors,
    matches,
    milestones,
    projects,
    webhooks,
)
from app.api.v1.admin import admin_router

# NOTE: the consultant feature is disabled for now (PRD parked). Its routes are
# unmounted and the models kept dormant — re-add `consultants.router` here and
# the admin consultant routes to revive it. See app/api/v1/consultants.py.
#
# Phase 2 endpoints are implemented per-slice in their own routers (matches,
# milestones, …) as each ships — no blanket 501-stub module. Deal room (P2-04)
# and due-diligence (P2-05) routers land when those slices are built.

# Root-level router (mounted without the /v1 prefix).
root_router = APIRouter()
root_router.include_router(health.router)

# Versioned router (mounted under /v1).
api_router = APIRouter(prefix="/v1")
api_router.include_router(investors.router)
api_router.include_router(matches.router)
api_router.include_router(projects.router)
api_router.include_router(countries.router)
api_router.include_router(content.router)
api_router.include_router(ai.router)
api_router.include_router(contact.router)
api_router.include_router(account.router)
api_router.include_router(webhooks.router)
api_router.include_router(milestones.router)
api_router.include_router(due_diligence.router)
api_router.include_router(admin_router)
