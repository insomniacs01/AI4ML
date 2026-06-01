from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import get_settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "selected_project_base": settings.selected_project_base,
        "execution_runtime": settings.execution_runtime_label,
        "task_executor": "codex",
        "executor_status": "available",
        "executor_detail": "FastAPI is configured to delegate task execution to the codex_use Node backend.",
        "codex_backend_url": settings.codex_backend_url,
        "codex_workspace_root": str(settings.codex_workspace_root),
        "storage_dir": str(settings.storage_dir),
        "run_output_dir": str(settings.run_output_dir),
    }
