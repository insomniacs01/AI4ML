from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


if TYPE_CHECKING:
    from backend.app.core.config import Settings


PYTHON_RUNTIME_CHECK_MODULES = (
    "autogluon.assistant.cli.app",
    "pandas",
    "joblib",
    "sklearn",
    "reportlab",
    "rich",
    "typer",
)


def resolve_mamba_executable(path_hint: Path) -> str | None:
    """Resolve a configured mamba executable path or PATH-based command."""
    if path_hint.exists():
        return str(path_hint)

    candidates = [str(path_hint), path_hint.name, path_hint.stem, "mamba"]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def resolve_python_executable(path_hint: Path) -> str | None:
    """Resolve a configured Python executable path or PATH-based command."""
    if path_hint.exists():
        return str(path_hint)

    candidates = [str(path_hint), path_hint.name, path_hint.stem, "python"]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def python_runtime_unavailability_reason(path_hint: Path) -> str | None:
    resolved = resolve_python_executable(path_hint)
    if resolved is None:
        return f"python executable not found from {path_hint}"

    check_script = """
import importlib
import sys

modules = %s
for module_name in modules:
    try:
        importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        print(f"{module_name}: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        raise
""" % (repr(PYTHON_RUNTIME_CHECK_MODULES),)

    try:
        result = subprocess.run(  # noqa: S603
            [resolved, "-c", check_script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError as exc:
        return f"python runtime check failed: {exc}"
    except subprocess.TimeoutExpired:
        return f"python runtime check timed out for {resolved}"

    if result.returncode == 0:
        return None

    details = (result.stderr or result.stdout).strip()
    return (
        f"python runtime import check failed for {resolved}: "
        f"{details or f'exit code {result.returncode}'}"
    )


class LocalOpenAIProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runtime_dir = settings.mlzero_runtime_dir
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.runtime_dir / "llama_cpp_server.log"
        self.pid_path = self.runtime_dir / "llama_cpp_server.pid"

    def ensure_running(self, startup_timeout: int = 240) -> None:
        if self._is_healthy():
            return

        if not self.settings.mlzero_uses_local_provider:
            reason = self.unavailability_reason()
            if reason is None:
                raise RuntimeError("Cloud provider health changed between checks; retry the request after inspecting provider logs.")
            raise RuntimeError(
                "Cloud OpenAI-compatible provider did not pass the availability check. "
                f"{reason}"
            )

        self._stop_stale_process()
        self._start_server()

        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if self._is_healthy():
                return
            time.sleep(2)

        raise RuntimeError(
            "Local llama-cpp OpenAI provider did not become ready in time. "
            f"Check {self.log_path}."
        )

    def _start_server(self) -> None:
        policy_error = self._model_policy_error()
        if policy_error:
            raise RuntimeError(policy_error)
        mamba_executable = resolve_mamba_executable(self.settings.mlzero_mamba_executable)
        if mamba_executable is None:
            raise FileNotFoundError(
                f"MLZero mamba executable not found: {self.settings.mlzero_mamba_executable}"
            )
        if not self.settings.mlzero_model_path.exists():
            raise FileNotFoundError(
                f"MLZero local model file not found: {self.settings.mlzero_model_path}"
            )

        command = [
            mamba_executable,
            "run",
            "-n",
            self.settings.mlzero_env_name,
            "python",
            "-m",
            "llama_cpp.server",
            "--model",
            str(self.settings.mlzero_model_path),
            "--model_alias",
            self.settings.mlzero_model_alias,
            "--host",
            self.settings.mlzero_server_host,
            "--port",
            str(self.settings.mlzero_server_port),
            "--chat_format",
            self.settings.mlzero_chat_format,
            "--n_ctx",
            str(self.settings.mlzero_context_size),
            "--n_threads",
            str(self.settings.mlzero_server_threads),
            "--n_threads_batch",
            str(self.settings.mlzero_server_threads),
            "--use_mlock",
            "False",
            "--verbose",
            "False",
        ]

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        with self.log_path.open("ab") as log_file:
            popen_kwargs = {
                "cwd": str(self.settings.repo_root),
                "env": env,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True

            process = subprocess.Popen(command, **popen_kwargs)  # noqa: S603

        self.pid_path.write_text(str(process.pid), encoding="utf-8")

    def _stop_stale_process(self) -> None:
        if not self.pid_path.exists():
            return

        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            self.pid_path.unlink(missing_ok=True)
            return

        if not self._process_exists(pid):
            self.pid_path.unlink(missing_ok=True)
            return

        try:
            self._terminate_process(pid, force=False)
        except ProcessLookupError:
            self.pid_path.unlink(missing_ok=True)
            return

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not self._process_exists(pid):
                self.pid_path.unlink(missing_ok=True)
                return
            time.sleep(0.5)

        try:
            self._terminate_process(pid, force=True)
        except ProcessLookupError:
            pass
        finally:
            self.pid_path.unlink(missing_ok=True)

    def _is_healthy(self) -> bool:
        if self._model_policy_error():
            return False

        try:
            request = Request(
                self._models_url,
                headers=self._request_headers(),
            )
            with urlopen(request, timeout=self.settings.mlzero_provider_request_timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return False

        model_ids = [item.get("id", "") for item in payload.get("data", []) if isinstance(item, dict)]
        return self.settings.mlzero_model_alias in model_ids

    def unavailability_reason(self) -> str | None:
        policy_error = self._model_policy_error()
        if policy_error:
            return policy_error

        if self.settings.mlzero_uses_local_provider:
            if not self.settings.mlzero_model_path.exists():
                return f"local model file missing at {self.settings.mlzero_model_path}"
            if self._is_healthy():
                return None
            return (
                "local OpenAI-compatible provider is not responding at "
                f"{self.settings.mlzero_provider_base_url}/models"
            )

        if not self.settings.mlzero_openai_api_key or self.settings.mlzero_openai_api_key == "local":
            return "cloud provider api key is missing"

        try:
            request = Request(
                self._models_url,
                headers=self._request_headers(),
            )
            with urlopen(request, timeout=self.settings.mlzero_provider_request_timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return f"cloud provider returned HTTP {exc.code}: {body}"
        except (URLError, TimeoutError, OSError) as exc:
            return f"cloud provider request failed: {exc}"
        except json.JSONDecodeError as exc:
            return f"cloud provider returned invalid JSON: {exc}"

        model_ids = [item.get("id", "") for item in payload.get("data", []) if isinstance(item, dict)]
        if self.settings.mlzero_model_alias not in model_ids:
            return (
                "configured cloud model is not listed by the provider: "
                f"{self.settings.mlzero_model_alias}"
            )

        return None

    @property
    def _models_url(self) -> str:
        return f"{self.settings.mlzero_provider_base_url}/models"

    def _request_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"User-Agent": self.settings.mlzero_provider_user_agent}
        if not self.settings.mlzero_uses_local_provider:
            headers["Authorization"] = f"Bearer {self.settings.mlzero_openai_api_key}"
        return headers

    def _model_policy_error(self) -> str | None:
        if self.settings.mlzero_model_alias.startswith("Pro/"):
            return (
                "Pro models are blocked by project policy. "
                f"Configured model: {self.settings.mlzero_model_alias}"
            )
        return None

    @staticmethod
    def _process_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    @staticmethod
    def _terminate_process(pid: int, *, force: bool) -> None:
        if os.name == "nt":
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            return

        os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
