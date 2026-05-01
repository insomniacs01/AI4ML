from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.supabase_config import get_project_env_files


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MLZERO_PYTHON = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
    "python.exe" if os.name == "nt" else "python"
)


def _default_runtime_root() -> Path:
    """Keep MLZero runtime artifacts outside the repo.

    When developers run FastAPI with ``uvicorn --reload``, uvicorn watches Python
    files under the project tree. MLZero writes generated files such as
    ``generated_code.py`` into the run output directory; if that directory lives
    inside the repo, those files trigger an unwanted reload and interrupt the
    in-flight task.
    """
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
    run_output_dir: Path = DEFAULT_RUNTIME_ROOT / "mlzero_runs"
    mlzero_runtime_dir: Path = DEFAULT_RUNTIME_ROOT / "mlzero_runtime"
    mlzero_config_path: Path = REPO_ROOT / "backend" / "config" / "mlzero-local-openai.yaml"
    mlzero_model_path: Path = REPO_ROOT / "local" / "models" / "Qwen2.5-Coder-0.5B-Instruct-Q4_K_M.gguf"
    mlzero_mamba_executable: Path = Path.home() / ".local" / "miniforge3" / "bin" / "mamba"
    mlzero_execution_mode: Literal["mamba", "python"] = "mamba"
    mlzero_python_executable: Path = DEFAULT_MLZERO_PYTHON
    mlzero_env_name: str = "mlzero"
    mlzero_server_host: str = "127.0.0.1"
    mlzero_server_port: int = 8001
    mlzero_model_alias: str = "gpt-4-local"
    mlzero_chat_format: str = "chatml"
    mlzero_context_size: int = 4096
    mlzero_server_threads: int = -1
    mlzero_max_iterations: int = 6
    mlzero_continuous_improvement: bool = True
    mlzero_min_candidate_models: int = 3
    mlzero_openai_api_key: str = "local"
    mlzero_hf_endpoint: str = "https://hf-mirror.com"
    selected_project_base: str = "mlzero / autogluon-assistant"
    mlzero_provider_mode: Literal["local", "cloud"] = "local"
    mlzero_provider_base_url_override: str = ""
    mlzero_provider_wire_api: Literal["chat_completions", "responses"] = "chat_completions"
    mlzero_provider_user_agent: str = "Mozilla/5.0"
    mlzero_provider_request_timeout_seconds: int = 30
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
    supabase_timeout_seconds: int = 10

    @property
    def mlzero_provider_base_url(self) -> str:
        if self.mlzero_provider_base_url_override:
            return self.mlzero_provider_base_url_override.rstrip("/")
        return f"http://{self.mlzero_server_host}:{self.mlzero_server_port}/v1"

    @property
    def mlzero_uses_local_provider(self) -> bool:
        return self.mlzero_provider_mode == "local"

    @property
    def execution_runtime_label(self) -> str:
        runtime_label = "mamba env launcher" if self.mlzero_execution_mode == "mamba" else "python launcher"
        if self.mlzero_uses_local_provider:
            return f"mlzero + {runtime_label} + local openai-compatible llama-cpp"
        return f"mlzero + {runtime_label} + cloud openai-compatible provider"

    @property
    def supabase_rest_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/rest/v1"

    @property
    def supabase_auth_user_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/user"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    settings.run_output_dir.mkdir(parents=True, exist_ok=True)
    settings.mlzero_runtime_dir.mkdir(parents=True, exist_ok=True)
    return settings
