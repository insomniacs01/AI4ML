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
        "execution_runtime": settings.execution_runtime,
        "llm_mode": settings.llm_mode,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "provider_base_url": settings.mlzero_provider_base_url,
        "model_alias": settings.mlzero_model_alias,
        "storage_dir": str(settings.storage_dir),
        "run_output_dir": str(settings.run_output_dir),
        "mlzero_config_path": str(settings.mlzero_config_path),
    }
