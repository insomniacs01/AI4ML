from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import get_settings
from backend.app.services.executors.mlzero_executor import MLZeroExecutor


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    executor = MLZeroExecutor(settings)
    provider_reason = executor.provider_unavailability_reason()
    runtime_reason = executor.runtime_unavailability_reason()
    executor_reason = provider_reason or runtime_reason
    return {
        "status": "ok",
        "selected_project_base": settings.selected_project_base,
        "execution_runtime": settings.execution_runtime_label,
        "task_executor": "mlzero",
        "provider_mode": settings.mlzero_provider_mode,
        "execution_mode": settings.mlzero_execution_mode,
        "provider_status": "available" if provider_reason is None else "unavailable",
        "provider_detail": provider_reason or "OpenAI-compatible provider is available.",
        "executor_status": "available" if executor_reason is None else "unavailable",
        "executor_detail": executor_reason or "MLZero runtime is available on this machine.",
        "provider_base_url": settings.mlzero_provider_base_url,
        "provider_wire_api": settings.mlzero_provider_wire_api,
        "model_alias": settings.mlzero_model_alias,
        "runtime_python_executable": str(settings.mlzero_python_executable),
        "runtime_mamba_executable": str(settings.mlzero_mamba_executable),
        "storage_dir": str(settings.storage_dir),
        "run_output_dir": str(settings.run_output_dir),
    }
