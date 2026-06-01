from __future__ import annotations

import os
import secrets
from hashlib import sha256
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.supabase_config import get_project_env_files


REPO_ROOT = Path(__file__).resolve().parents[3]


def _default_runtime_root() -> Path:
    """Keep runtime artifacts outside the repo to avoid dev-server reload loops."""
    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "AI4ML"
        return Path.home() / "AppData" / "Local" / "AI4ML"

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home) / "ai4ml"
    return Path.home() / ".local" / "state" / "ai4ml"


DEFAULT_RUNTIME_ROOT = _default_runtime_root()


def _default_backend_instance_lock_path() -> Path:
    repo_key = sha256(str(REPO_ROOT).encode("utf-8")).hexdigest()[:12]
    return DEFAULT_RUNTIME_ROOT / f"backend-{repo_key}.lock"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI4ML_",
        extra="ignore",
        env_file=get_project_env_files(REPO_ROOT),
        env_file_encoding="utf-8",
    )

    app_name: str = "AI4ML Backend"
    api_prefix: str = "/api"
    repo_root: Path = REPO_ROOT
    storage_dir: Path = REPO_ROOT / "storage" / "tasks"
    run_output_dir: Path = DEFAULT_RUNTIME_ROOT / "runs"
    codex_backend_url: str = "http://127.0.0.1:3000"
    codex_request_timeout_seconds: int = 30
    codex_workspace_root: Path = REPO_ROOT / "codex_use" / "workspaces"
    codex_config_dir: Path = Path.home() / ".codex"
    backend_instance_lock_path: Path = Field(default_factory=_default_backend_instance_lock_path)
    selected_project_base: str = "codex_use / Codex"
    ai_provider_base_url: str = ""
    ai_provider_api_key: str = ""
    ai_provider_model_name: str = ""
    ai_provider_wire_api: Literal["chat_completions", "responses"] = "chat_completions"
    ai_provider_user_agent: str = "Mozilla/5.0"
    ai_provider_request_timeout_seconds: int = 180
    ai_provider_tokenizer_model_alias: str = ""
    connector_secret_key: str = ""

    # ---- User / Auth settings ----
    jwt_secret_key: str = secrets.token_urlsafe(32)
    jwt_expire_minutes: int = 720  # 12 hours
    user_storage_dir: Path = REPO_ROOT / "storage" / "users"
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices("AI4ML_SUPABASE_URL", "VITE_SUPABASE_URL"),
    )
    supabase_publishable_key: str = Field(
        default="",
        validation_alias=AliasChoices("AI4ML_SUPABASE_PUBLISHABLE_KEY", "VITE_SUPABASE_PUBLISHABLE_KEY"),
    )
    supabase_service_role_key: str = Field(
        default="",
        validation_alias=AliasChoices("AI4ML_SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_timeout_seconds: int = 10

    @property
    def execution_runtime_label(self) -> str:
        return f"codex_use node backend at {self.codex_backend_url.rstrip('/')}"

    @property
    def supabase_rest_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/rest/v1"

    @property
    def supabase_auth_user_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/user"

    @property
    def supabase_auth_admin_users_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/admin/users"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)

    @property
    def supabase_admin_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.run_output_dir.mkdir(parents=True, exist_ok=True)
    return settings
