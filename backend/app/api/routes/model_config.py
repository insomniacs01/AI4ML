from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_admin_access
from backend.app.services.model_config import read_model_config, read_model_profile, save_model_config


router = APIRouter(prefix="/model-config", tags=["model-config"])


class ModelProfileResponse(BaseModel):
    display_name: str


class ModelConfigResponse(ModelProfileResponse):
    auth_json: str
    config_toml: str
    auth_path: str
    config_path: str
    auth_configured: bool = False
    auth_key_preview: str = "未配置"
    reload: dict[str, Any] | None = None


class ModelConfigUpdateRequest(BaseModel):
    display_name: str = Field(default="Codex", max_length=48)
    auth_json: str = ""
    config_toml: str = ""
    api_key: str = ""


@router.get("/profile", response_model=ModelProfileResponse)
def get_model_profile(
    team_access: TeamAccessContext = Depends(require_team_access),
) -> dict[str, str]:
    return read_model_profile(get_settings())


@router.get("", response_model=ModelConfigResponse)
def get_current_model_config(
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> dict[str, Any]:
    return read_model_config(get_settings())


@router.put("", response_model=ModelConfigResponse)
def update_current_model_config(
    payload: ModelConfigUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> dict[str, Any]:
    try:
        return save_model_config(
            get_settings(),
            display_name=payload.display_name,
            config_toml=payload.config_toml,
            api_key=payload.api_key,
            auth_json=payload.auth_json,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存模型配置失败：{exc}",
        ) from exc
