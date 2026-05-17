from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.routes.task_human import router as task_human_router
from backend.app.api.routes.task_lifecycle import router as task_lifecycle_router
from backend.app.api.routes.task_route_common import (
    _RoutingRuntimeContext,
    _resolve_preferred_selection,
    _validate_task_stage_routing_overrides,
)
from backend.app.api.routes.task_runtime import router as task_runtime_router

router = APIRouter(tags=["tasks"])
router.include_router(task_lifecycle_router, prefix="/tasks")
router.include_router(task_runtime_router, prefix="/tasks")
router.include_router(task_human_router, prefix="/tasks")
