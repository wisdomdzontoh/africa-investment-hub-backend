"""Admin API — all routes require the ``admin`` role (PRD §13)."""

from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.api.v1.admin import cms, operations

# Single admin router; role enforced once at the group level (and re-checked
# server-side in each handler's dependencies).
admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
admin_router.include_router(operations.router)
admin_router.include_router(cms.router)
