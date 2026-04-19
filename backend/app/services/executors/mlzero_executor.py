from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.models.task import RunSummary, TaskRecord
from backend.app.services.executors.base import BaseExecutor
from backend.app.services.mlzero_runtime import LocalOpenAIProvider


BEST_SCORE_RE = re.compile(r"Best score:\s*([+-]?\d+(?:\.\d+)?)\s+from node\s+(\d+)\s+using\s+(.+)")
NODE_SCORE_RE = re.compile(r"Node\s+(\d+)\s+\(([^)]+)\):\s+([+-]?\d+(?:\.\d+)?)")
COMPLETION_RE = re.compile(
    r"Task completed successfully!\s*Best node:\s*(\d+)\s+with validation score\s+([^\s]+)"
)


class MLZeroExecutor(BaseExecutor):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.output_root = settings.run_output_dir
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.provider = LocalOpenAIProvider(settings)

    def run(self, task: TaskRecord, dataset_path: Path, time_limit: int) -> RunSummary:
        if not self.settings.mlzero_config_path.exists():
            raise FileNotFoundError(
                f"MLZero config file not found: {self.settings.mlzero_config_path}"
            )
        if self.settings.llm_mode == "local":
            self.provider.ensure_running()

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = self.output_root / task.id / run_id
        input_dir = output_dir / "input"
        output_dir.mkdir(parents=True, exist_ok=True)
        self._prepare_input_bundle(task, dataset_path, input_dir)

        env = self._build_llm_environment()
        env["HF_ENDPOINT"] = self.settings.mlzero_hf_endpoint
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"

        command = [
            str(self.settings.mlzero_mamba_executable),
            "run",
            "-n",
            self.settings.mlzero_env_name,
            "mlzero",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            str(self.settings.mlzero_config_path),
            "--provider",
            self.settings.llm_provider,
            "-n",
            str(self.settings.mlzero_max_iterations),
            "--initial-instruction",
            self._build_initial_instruction(task),
            "-v",
            "1",
        ]

        timeout_seconds = max(300, time_limit * 60)

        try:
            result = subprocess.run(  # noqa: S603
                command,
                cwd=str(self.settings.repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"MLZero timed out after {timeout_seconds} seconds. "
                f"Output directory: {output_dir}"
            ) from exc

        stdout_path = output_dir / "mlzero_stdout.log"
        stderr_path = output_dir / "mlzero_stderr.log"
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")

        if result.returncode != 0:
            raise RuntimeError(self._build_failure_message(result, output_dir))

        return self._build_summary(output_dir, result.stdout)

    def _prepare_input_bundle(self, task: TaskRecord, dataset_path: Path, input_dir: Path) -> None:
        input_dir.mkdir(parents=True, exist_ok=True)

        target_dataset_path = input_dir / "train.csv"
        shutil.copy2(dataset_path, target_dataset_path)

        metric_name = "accuracy" if task.problem_type == "classification" else "rmse"
        description_lines = [
            f"Task name: {task.name}",
            f"Task description: {task.description}",
            f"Problem type: {task.problem_type}",
            f"Label column: {task.label_column}",
            f"Preferred validation metric: {metric_name}",
            "Use the provided train.csv as the primary dataset.",
            "Create a reproducible local baseline and print the final validation score clearly.",
            "Prefer lightweight libraries already installed in the environment, especially scikit-learn.",
        ]
        (input_dir / "descriptions.txt").write_text("\n".join(description_lines), encoding="utf-8")

    def _build_initial_instruction(self, task: TaskRecord) -> str:
        if task.problem_type == "classification":
            metric_hint = "Report validation accuracy as a numeric score."
        else:
            metric_hint = "Report validation RMSE as a numeric score."

        return (
            f"Solve the task '{task.name}' using train.csv. "
            f"The label column is '{task.label_column}' and the problem type is {task.problem_type}. "
            "Use a simple, reliable local baseline that can run on CPU with installed packages. "
            f"{metric_hint} Save useful outputs into the provided output folder."
        )

    def _build_summary(self, output_dir: Path, stdout: str) -> RunSummary:
        summary_path = next(iter(sorted(output_dir.glob("node_*/states/best_run_summary.txt"))), None)
        summary_text = summary_path.read_text(encoding="utf-8") if summary_path else ""

        leaderboard: list[dict[str, object]] = []
        for node_id, tool_used, score in NODE_SCORE_RE.findall(summary_text):
            leaderboard.append(
                {
                    "node": f"node_{node_id}",
                    "tool": tool_used.strip(),
                    "validation_score": float(score),
                }
            )

        best_model = "mlzero-best-run"
        metric_value = 0.0

        best_match = BEST_SCORE_RE.search(summary_text)
        if best_match:
            metric_value = float(best_match.group(1))
            best_model = f"node_{best_match.group(2)} / {best_match.group(3).strip()}"
        else:
            completion_match = COMPLETION_RE.search(stdout)
            if completion_match:
                best_model = f"node_{completion_match.group(1)}"
                try:
                    metric_value = float(completion_match.group(2))
                except ValueError:
                    metric_value = 0.0

        return RunSummary(
            best_model=best_model,
            metric_name="validation_score",
            metric_value=metric_value,
            leaderboard=leaderboard,
            output_dir=str(output_dir),
        )

    def _build_failure_message(self, result: subprocess.CompletedProcess[str], output_dir: Path) -> str:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-20:])
        stdout_tail = "\n".join(result.stdout.strip().splitlines()[-20:])
        return (
            "MLZero run failed.\n"
            f"Output directory: {output_dir}\n"
            "STDOUT tail:\n"
            f"{stdout_tail or '<empty>'}\n"
            "STDERR tail:\n"
            f"{stderr_tail or '<empty>'}"
        )

    def _build_llm_environment(self) -> dict[str, str]:
        env = os.environ.copy()

        if self.settings.llm_provider == "openai":
            if self.settings.llm_mode == "local":
                env["OPENAI_API_KEY"] = self.settings.mlzero_openai_api_key
                env["OPENAI_BASE_URL"] = self.settings.mlzero_provider_base_url
            else:
                if not self.settings.llm_api_key:
                    raise RuntimeError("AI4ML_LLM_API_KEY is required for remote OpenAI-compatible providers.")
                env["OPENAI_API_KEY"] = self.settings.llm_api_key
                if self.settings.llm_base_url:
                    env["OPENAI_BASE_URL"] = self.settings.llm_base_url
                else:
                    env.pop("OPENAI_BASE_URL", None)
        elif self.settings.llm_provider == "anthropic":
            if not self.settings.anthropic_api_key:
                raise RuntimeError("AI4ML_ANTHROPIC_API_KEY is required for provider=anthropic.")
            env["ANTHROPIC_API_KEY"] = self.settings.anthropic_api_key
        elif self.settings.llm_provider == "azure":
            if not self.settings.azure_openai_api_key:
                raise RuntimeError("AI4ML_AZURE_OPENAI_API_KEY is required for provider=azure.")
            if not self.settings.azure_openai_endpoint:
                raise RuntimeError("AI4ML_AZURE_OPENAI_ENDPOINT is required for provider=azure.")
            if not self.settings.openai_api_version:
                raise RuntimeError("AI4ML_OPENAI_API_VERSION is required for provider=azure.")
            env["AZURE_OPENAI_API_KEY"] = self.settings.azure_openai_api_key
            env["AZURE_OPENAI_ENDPOINT"] = self.settings.azure_openai_endpoint
            env["OPENAI_API_VERSION"] = self.settings.openai_api_version
        else:
            raise RuntimeError(
                f"Unsupported AI4ML_LLM_PROVIDER='{self.settings.llm_provider}'. "
                "Use one of: openai, anthropic, azure."
            )

        return env
