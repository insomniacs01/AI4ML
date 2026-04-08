from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


if TYPE_CHECKING:
    from backend.app.core.config import Settings


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
        if not self.settings.mlzero_mamba_executable.exists():
            raise FileNotFoundError(
                f"MLZero mamba executable not found: {self.settings.mlzero_mamba_executable}"
            )
        if not self.settings.mlzero_model_path.exists():
            raise FileNotFoundError(
                f"MLZero local model file not found: {self.settings.mlzero_model_path}"
            )

        command = [
            str(self.settings.mlzero_mamba_executable),
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
        env.setdefault("PYTHONUNBUFFERED", "1")

        with self.log_path.open("ab") as log_file:
            process = subprocess.Popen(  # noqa: S603
                command,
                cwd=str(self.settings.repo_root),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

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
            os.killpg(pid, signal.SIGTERM)
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
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            self.pid_path.unlink(missing_ok=True)

    def _is_healthy(self) -> bool:
        try:
            with urlopen(f"{self.settings.mlzero_provider_base_url}/models", timeout=5) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return False

        model_ids = [item.get("id", "") for item in payload.get("data", []) if isinstance(item, dict)]
        return self.settings.mlzero_model_alias in model_ids

    @staticmethod
    def _process_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
