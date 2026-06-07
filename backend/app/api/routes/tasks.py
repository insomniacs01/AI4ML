from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.routes.task_chat import router as task_chat_router
from backend.app.api.routes.task_dataset import router as task_dataset_router
from backend.app.api.routes.task_human import router as task_human_router
from backend.app.api.routes.task_lifecycle import router as task_lifecycle_router
from backend.app.api.routes.task_run import router as task_run_router
from backend.app.api.routes.task_runtime import router as task_runtime_router

router = APIRouter(tags=["tasks"])
router.include_router(task_lifecycle_router, prefix="/tasks")
router.include_router(task_dataset_router, prefix="/tasks")
router.include_router(task_runtime_router, prefix="/tasks")
router.include_router(task_chat_router, prefix="/tasks")
router.include_router(task_run_router, prefix="/tasks")
router.include_router(task_human_router, prefix="/tasks")
