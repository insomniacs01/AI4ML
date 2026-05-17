from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import RunSummary, TaskRecord
from backend.app.services.executors.base import BaseExecutor
from backend.app.services.task_human_context import (
    build_task_human_description_appendix,
    build_task_human_guidance_lines,
    build_task_human_initial_instruction_note,
    build_task_human_instruction_file,
)
from backend.app.services.mlzero_runtime import (
    LocalOpenAIProvider,
    python_runtime_unavailability_reason,
    resolve_mamba_executable,
    resolve_python_executable,
)
from backend.app.services.token_usage import read_mlzero_token_usage


AUTOGLUON_OPTIONAL_MODULES: tuple[tuple[str, str], ...] = (
    ("lightgbm", "GBM"),
    ("xgboost", "XGB"),
    ("catboost", "CAT"),
    ("torch", "NN_TORCH"),
    ("fastai", "FASTAI"),
    ("tabpfn", "TABPFNV2"),
    ("tabicl", "TABICL"),
    ("tabm", "TABM"),
)
AUTOGLUON_BUILTIN_MODEL_FAMILIES: tuple[str, ...] = ("RF", "XT", "KNN")


def _safe_path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


class MLZeroRunError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        output_dir: Path | str | None = None,
        recoverable: bool = False,
        retry_stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.output_dir = str(output_dir) if output_dir is not None else None
        self.token_usage = read_mlzero_token_usage(output_dir) if output_dir is not None else None
        self.recoverable = recoverable
        self.retry_stage = retry_stage


class MLZeroExecutor(BaseExecutor):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.output_root = settings.run_output_dir
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.provider = LocalOpenAIProvider(settings)

    def run(self, task: TaskRecord, dataset_path: Path, time_limit: int | None = None) -> RunSummary:
        if not self.settings.mlzero_config_path.exists():
            raise FileNotFoundError(
                f"MLZero config file not found: {self.settings.mlzero_config_path}"
            )
        self.provider.ensure_running()
        max_iterations, continuous_improvement = self._resolve_search_plan(time_limit)

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = self.output_root / task.id / run_id
        input_dir = output_dir / "input"
        output_dir.mkdir(parents=True, exist_ok=True)
        self._prepare_input_bundle(task, dataset_path, input_dir)
        runtime_config_path = self._build_runtime_config(
            output_dir,
            continuous_improvement=continuous_improvement,
        )

        env = self._build_runtime_env()

        command = self._build_command(
            input_dir,
            output_dir,
            runtime_config_path,
            task,
            max_iterations=max_iterations,
            continuous_improvement=continuous_improvement,
        )

        stdout_path = output_dir / "mlzero_stdout.log"
        stderr_path = output_dir / "mlzero_stderr.log"
        result = self._run_once(
            command=command,
            output_dir=output_dir,
            env=env,
            timeout_seconds=None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        if result.returncode != 0 and self._is_transient_provider_timeout(result, output_dir):
            retry_env = {**env, "OPENAI_REQUEST_TIMEOUT": str(max(300, self.settings.mlzero_provider_request_timeout_seconds))}
            self._append_repair_note(
                output_dir,
                "检测到 LLM 请求超时，自动提高单次请求 timeout 并重试一次。",
            )
            retry_result = self._run_once(
                command=command,
                output_dir=output_dir,
                env=retry_env,
                timeout_seconds=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                append_logs=True,
            )
            if retry_result.returncode == 0:
                result = retry_result
            else:
                result = retry_result

        if result.returncode != 0:
            raise MLZeroRunError(
                self._build_failure_message(result, output_dir),
                output_dir=output_dir,
                recoverable=self._is_recoverable_failure(result, output_dir),
                retry_stage=self._infer_retry_stage(result, output_dir),
            )

        try:
            return self._build_summary(output_dir, task=task)
        except Exception as exc:  # noqa: BLE001
            raise MLZeroRunError(
                str(exc),
                output_dir=output_dir,
                recoverable=True,
                retry_stage="report_generation",
            ) from exc

    def _build_runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = self.settings.mlzero_openai_api_key
        env["OPENAI_BASE_URL"] = self.settings.mlzero_provider_base_url
        env["OPENAI_WIRE_API"] = self.settings.mlzero_provider_wire_api
        env["OPENAI_USER_AGENT"] = self.settings.mlzero_provider_user_agent
        request_timeout = max(180, self.settings.mlzero_provider_request_timeout_seconds)
        env["OPENAI_REQUEST_TIMEOUT"] = str(request_timeout)
        env["HF_ENDPOINT"] = self.settings.mlzero_hf_endpoint
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        python_executable = resolve_python_executable(self.settings.mlzero_python_executable) or sys.executable
        env["AI4ML_PYTHON_EXECUTABLE"] = python_executable
        python_dir = str(Path(python_executable).parent)
        env["PATH"] = f"{python_dir}{os.pathsep}{env.get('PATH', '')}"
        return env

    def _run_once(
        self,
        *,
        command: list[str],
        output_dir: Path,
        env: dict[str, str],
        timeout_seconds: int | None,
        stdout_path: Path,
        stderr_path: Path,
        append_logs: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self._run_command_with_live_logs(
                command,
                cwd=self.settings.repo_root,
                env=env,
                timeout_seconds=timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                append=append_logs,
            )
        except subprocess.TimeoutExpired as exc:
            raise MLZeroRunError(
                f"MLZero timed out after {timeout_seconds} seconds. "
                f"Output directory: {output_dir}",
                recoverable=True,
                retry_stage="training_validation",
                output_dir=output_dir,
            ) from exc

    def _run_command_with_live_logs(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int | None,
        stdout_path: Path,
        stderr_path: Path,
        append: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_path.parent.mkdir(parents=True, exist_ok=True)

        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            raise RuntimeError("MLZero process did not expose stdout/stderr pipes; live log capture cannot start.")

        def pump_stream(stream: Any, target_path: Path, chunks: list[str]) -> None:
            mode = "a" if append else "w"
            with target_path.open(mode, encoding="utf-8", errors="replace") as handle:
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    handle.write(line)
                    handle.flush()

        stdout_thread = threading.Thread(target=pump_stream, args=(process.stdout, stdout_path, stdout_chunks), daemon=True)
        stderr_thread = threading.Thread(target=pump_stream, args=(process.stderr, stderr_path, stderr_chunks), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            returncode = process.wait()
            timeout_line = f"\nMLZero timed out after {timeout_seconds} seconds and was terminated by AI4ML.\n"
            stderr_chunks.append(timeout_line)
            with stderr_path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(timeout_line)
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            raise subprocess.TimeoutExpired(
                cmd=exc.cmd,
                timeout=exc.timeout,
                output="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
            ) from exc

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
        )

    def _prepare_input_bundle(self, task: TaskRecord, dataset_path: Path, input_dir: Path) -> None:
        input_dir.mkdir(parents=True, exist_ok=True)

        target_dataset_path = input_dir / "train.csv"
        shutil.copy2(dataset_path, target_dataset_path)
        autogluon_runtime_guidance = self._autogluon_runtime_guidance_lines()
        human_guidance_lines = build_task_human_guidance_lines(task)

        description_lines = [
            f"Task name: {task.name}",
            f"Task description: {task.description}",
            "Use the provided train.csv as the primary dataset.",
            "Only train.csv is guaranteed to exist. Do not assume test.csv, validation.csv, or any other file exists unless you first verify it in the input folder.",
            "Read the provided train.csv and validate the task against the actual data.",
            "Create your own train/validation split from train.csv when you need validation. Do not require a separate test file for this task.",
            "If AI-parsed task metadata is provided below, treat it as the preferred interpretation unless the CSV clearly contradicts it.",
            "If a label column is provided below, use that exact column as the target. Never silently replace it with the last CSV column.",
            "If generated code fails because of CSV parsing, column names, dtypes, missing values, or model assumptions, inspect the error and revise the code instead of requiring precomputed task metadata.",
            f"When labeled training data is available, compare at least {self.settings.mlzero_min_candidate_models} candidate models or use an AutoML library that internally compares multiple candidates.",
            "For tabular classification and regression in this project runtime, use autogluon.tabular and fix its configuration directly instead of switching libraries.",
            "Persist machine-readable artifacts in the output folder: run_summary.json plus leaderboard.json or leaderboard.csv.",
            "run_summary.json must include exact keys best_model, metric_name, metric_value, validation_score, tool, candidate_model_count, target_column, and problem_type.",
            "Each leaderboard row must include exact fields model and validation_score, and should include fit_time and pred_time when available.",
            "During model training, also create telemetry/training_metrics.ndjson under the output folder when the underlying library exposes progress. Write one JSON object per line with keys such as model, epoch, total_epochs, iteration, total_iterations, train_loss, validation_loss, validation_score, and metric_name. If the selected model family has no epoch/loss concept, do not invent those values; rely on leaderboard and fit_time instead.",
            "Do not stop after a single simple baseline if multiple candidate models are feasible within the time budget.",
        ]
        description_lines.extend(autogluon_runtime_guidance)
        if task.label_column:
            description_lines.append(f"Label column: {task.label_column}")
        if task.problem_type:
            description_lines.append(f"Problem type: {task.problem_type}")
        if task.structured_requirements:
            metric_name = task.structured_requirements.get("metric_name")
            reasoning = task.structured_requirements.get("reasoning")
            if isinstance(metric_name, str) and metric_name.strip():
                description_lines.append(f"Metric: {metric_name.strip()}")
            if isinstance(reasoning, str) and reasoning.strip():
                description_lines.append(f"AI analysis notes: {reasoning.strip()}")
        description_appendix = build_task_human_description_appendix(task)
        if description_appendix:
            description_lines.extend(description_appendix.splitlines())
        (input_dir / "descriptions.txt").write_text("\n".join(description_lines), encoding="utf-8")

        human_instruction_file = build_task_human_instruction_file(task)
        if human_instruction_file:
            (input_dir / "human_collaboration_instructions.txt").write_text(
                human_instruction_file,
                encoding="utf-8",
            )

    def _build_initial_instruction(self, task: TaskRecord) -> str:
        analysis_hint = ""
        autogluon_runtime_guidance = " ".join(self._autogluon_runtime_guidance_lines())
        human_guidance_lines = build_task_human_guidance_lines(task)
        if task.label_column:
            analysis_hint += f" Use label column '{task.label_column}'."
        if task.problem_type:
            if task.problem_type == "classification":
                analysis_hint += (
                    " Treat this as a classification problem, but when using autogluon.tabular, "
                    "map it to 'binary' or 'multiclass' after inspecting the number of distinct labels."
                )
            else:
                analysis_hint += f" Treat this as a {task.problem_type} problem."
        if task.structured_requirements:
            metric_name = task.structured_requirements.get("metric_name")
            if isinstance(metric_name, str) and metric_name.strip():
                analysis_hint += f" Prefer reporting {metric_name.strip()} as the validation metric."
        human_instruction_note = build_task_human_initial_instruction_note(task)
        if human_instruction_note:
            analysis_hint += f" {human_instruction_note}"
        return (
            f"Solve the task '{task.name}' using train.csv. "
            f"User request: {task.description}. "
            "Read the CSV yourself, inspect the columns and sample values, and use any provided AI-parsed task metadata as the default interpretation. "
            "If a label column is provided, use that exact column as the target and do not replace it with the last CSV column. "
            "Assume train.csv is the only guaranteed dataset file unless you explicitly verify otherwise. "
            "Do not assume test.csv exists; if you need validation, split train.csv yourself. "
            "Write and run the required data loading, preprocessing, training, and validation code. "
            "If the code fails, use the concrete error message to fix the code and continue. "
            f"Evaluate at least {self.settings.mlzero_min_candidate_models} candidate models when labeled training data is available. "
            "For tabular classification and regression in this project runtime, use autogluon.tabular and correct its configuration directly instead of switching to sklearn or another library. "
            "Save a machine-readable run_summary.json and leaderboard.json or leaderboard.csv into the provided output folder. "
            "run_summary.json must include exact keys best_model, metric_name, metric_value, validation_score, tool, candidate_model_count, target_column, and problem_type. "
            "Each leaderboard row must include exact fields model and validation_score, and should include fit_time and pred_time when available. "
            "If the training library exposes live progress, write telemetry/training_metrics.ndjson with one JSON object per line; do not invent epoch or loss values for models that do not report them. "
            "If the user-facing metric is lower-is-better, still persist a higher-is-better validation_score for search while also saving the raw metric in run_summary.json. "
            "Report the selected target column, inferred problem type, best model, metric name, final metric value, and final validation_score candidate ranking score. "
            f"{autogluon_runtime_guidance} "
            "Save useful outputs into the provided output folder."
            f"{' Human-reviewed decisions: ' + ' '.join(human_guidance_lines) if human_guidance_lines else ''}"
            f"{analysis_hint}"
        )

    @staticmethod
    def _module_available(module_name: str) -> bool:
        try:
            return find_spec(module_name) is not None
        except ModuleNotFoundError:
            return False

    def _autogluon_allowed_model_families(self) -> list[str]:
        families = list(AUTOGLUON_BUILTIN_MODEL_FAMILIES)
        for module_name, family_name in AUTOGLUON_OPTIONAL_MODULES:
            if self._module_available(module_name):
                families.append(family_name)
        return families

    def _autogluon_runtime_guidance_lines(self) -> list[str]:
        available_modules = [
            module_name for module_name, _family_name in AUTOGLUON_OPTIONAL_MODULES if self._module_available(module_name)
        ]
        missing_modules = [
            module_name for module_name, _family_name in AUTOGLUON_OPTIONAL_MODULES if not self._module_available(module_name)
        ]
        available_text = ", ".join(available_modules) if available_modules else "none"
        missing_text = ", ".join(missing_modules) if missing_modules else "none"
        allowed_families = ", ".join(self._autogluon_allowed_model_families())
        lines = [
            f"Runtime-verified autogluon optional modules available: {available_text}. Missing: {missing_text}.",
            f"When using autogluon.tabular here, restrict fit() hyperparameters to these verified model families: {allowed_families}.",
            "Do not manually log-transform, scale, or otherwise transform the target column for AutoGluon unless you also inverse-transform predictions and compute the saved metric_value on the original target scale. Prefer leaving the target on its original scale.",
            "Do not use presets such as extreme, extreme_quality, best, best_quality, high, high_quality, good, good_quality, or any zeroshot/tabarena/foundation-model portfolio in this runtime.",
            "Do not write a secondary sklearn implementation path. If an autogluon.tabular run fails, fix the AutoGluon configuration, API usage, or data handling and rerun with autogluon.tabular.",
            "In AutoGluon 1.4, use predictor.model_best or the top leaderboard row to identify the best model. Do not call predictor.get_model_best().",
            "Before saving leaderboard.json or leaderboard.csv, normalize AutoGluon leaderboard() output to the project's canonical schema. Each row must use exact fields model and validation_score, and should rename fit_time/pred_time from raw AutoGluon columns such as fit_time and pred_time_val when available.",
            "Do not persist a raw AutoGluon leaderboard with score_val or pred_time_val as the final artifact names; rename those columns before writing the saved leaderboard file.",
            "AutoGluon does not accept the generic problem_type value 'classification'. Infer the label cardinality first and pass 'binary' for 2 classes or 'multiclass' for more than 2 classes.",
            "For large tabular datasets, keep tree models bounded, for example RF/XT n_estimators around 30-80, and drop obvious file/path/provenance identifier columns such as Source_File when they are not the prediction target.",
            "Do not pass a fit(time_limit=...) value to AutoGluon unless the user explicitly asks for one; let training finish instead of cutting it short.",
        ]
        return lines

    @staticmethod
    def _coerce_float(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                result = float(stripped)
            except ValueError:
                return None
        else:
            return None
        if result != result or result in (float("inf"), float("-inf")):
            return None
        return result

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(stripped)
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_str(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _unique_existing_paths(paths: list[Path]) -> list[Path]:
        unique_paths: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            if not path.exists():
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(path)
        return unique_paths

    def _find_run_summary_paths(self, output_dir: Path) -> list[Path]:
        candidates = [
            output_dir / "best_run" / "output" / "run_summary.json",
            output_dir / "run_summary.json",
            *output_dir.glob("node_*/output/run_summary.json"),
        ]
        existing = [path for path in candidates if path.exists() and path.is_file()]
        return self._unique_existing_paths(
            sorted(existing, key=lambda path: (_safe_path_mtime(path), str(path)), reverse=True)
        )

    def _read_run_summary_payload(self, output_dir: Path) -> tuple[dict[str, Any] | None, Path | None]:
        for summary_path in self._find_run_summary_paths(output_dir):
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable run_summary.json at %s: %s", summary_path, exc)
                continue
            if isinstance(payload, dict):
                return payload, summary_path
            logger.warning("Skipping non-object run_summary.json at %s.", summary_path)
        return None, None

    def _require_run_summary_payload(self, output_dir: Path) -> tuple[dict[str, Any], Path]:
        payload, summary_path = self._read_run_summary_payload(output_dir)
        if payload is None or summary_path is None:
            raise RuntimeError(
                f"MLZero completed but did not produce a readable run_summary.json in {output_dir}"
            )
        return payload, summary_path

    def _require_summary_string(self, payload: dict[str, Any], key: str) -> str:
        value = self._coerce_str(payload.get(key))
        if value is None:
            raise RuntimeError(f"run_summary.json is missing a non-empty string field '{key}'.")
        return value

    def _require_summary_float(self, payload: dict[str, Any], key: str) -> float:
        value = self._coerce_float(payload.get(key))
        if value is None:
            raise RuntimeError(f"run_summary.json is missing a numeric field '{key}'.")
        return value

    def _require_summary_int(self, payload: dict[str, Any], key: str) -> int:
        value = self._coerce_int(payload.get(key))
        if value is None:
            raise RuntimeError(f"run_summary.json is missing an integer field '{key}'.")
        return value

    def _extract_inline_leaderboard_rows(self, payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if payload is None:
            return []
        rows = payload.get("leaderboard")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return []

    def _find_leaderboard_paths(
        self,
        output_dir: Path,
        run_summary_path: Path | None,
        payload: dict[str, Any] | None,
    ) -> list[Path]:
        paths: list[Path] = []

        if payload is not None and run_summary_path is not None:
            for key in ("leaderboard_path", "leaderboard_file", "leaderboard_json_path", "leaderboard_csv_path"):
                relative_path = self._coerce_str(payload.get(key))
                if relative_path:
                    paths.append(run_summary_path.parent / relative_path)

        if run_summary_path is not None:
            paths.extend(
                [
                    run_summary_path.parent / "leaderboard.json",
                    run_summary_path.parent / "leaderboard.csv",
                ]
            )

        paths.extend(
            [
                output_dir / "best_run" / "output" / "leaderboard.json",
                output_dir / "best_run" / "output" / "leaderboard.csv",
                output_dir / "leaderboard.json",
                output_dir / "leaderboard.csv",
            ]
        )
        return self._unique_existing_paths(paths)

    def _first_int(self, row: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = self._coerce_int(row.get(key))
            if value is not None:
                return value
        return None

    def _normalize_leaderboard_row(
        self,
        row: dict[str, Any],
        *,
        index: int,
        default_metric_name: str,
        default_tool_name: str | None,
    ) -> dict[str, object]:
        validation_score = self._coerce_float(row.get("validation_score"))
        if validation_score is None:
            raise RuntimeError(f"Leaderboard row {index + 1} is missing numeric validation_score.")

        model_name = self._coerce_str(row.get("model"))
        if model_name is None:
            raise RuntimeError(f"Leaderboard row {index + 1} is missing non-empty model.")

        metric_name = self._coerce_str(row.get("metric_name")) or default_metric_name
        metric_value = self._coerce_float(row.get("metric_value"))
        fit_time = self._coerce_float(row.get("fit_time"))
        pred_time = self._coerce_float(row.get("pred_time"))

        normalized: dict[str, object] = {
            "rank": self._first_int(row, ("rank",)) or (index + 1),
            "model": model_name,
            "metric_name": metric_name,
            "validation_score": validation_score,
        }

        node_name = self._coerce_str(row.get("node"))
        tool_name = self._coerce_str(row.get("tool")) or default_tool_name
        if node_name:
            normalized["node"] = node_name
        if tool_name:
            normalized["tool"] = tool_name
        if metric_value is not None and abs(metric_value - validation_score) > 1e-12:
            normalized["metric_value"] = metric_value
        if fit_time is not None:
            normalized["fit_time"] = fit_time
        if pred_time is not None:
            normalized["pred_time"] = pred_time
        return normalized

    def _parse_leaderboard_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        default_metric_name: str,
        default_tool_name: str | None,
    ) -> list[dict[str, object]]:
        leaderboard: list[dict[str, object]] = []
        for index, row in enumerate(rows):
            normalized = self._normalize_leaderboard_row(
                row,
                index=index,
                default_metric_name=default_metric_name,
                default_tool_name=default_tool_name,
            )
            leaderboard.append(normalized)
        return leaderboard

    def _load_leaderboard_entries(
        self,
        output_dir: Path,
        *,
        run_summary_payload: dict[str, Any],
        run_summary_path: Path,
        default_metric_name: str,
        default_tool_name: str | None,
    ) -> list[dict[str, object]]:
        inline_rows = self._extract_inline_leaderboard_rows(run_summary_payload)
        if inline_rows:
            return self._parse_leaderboard_rows(
                inline_rows,
                default_metric_name=default_metric_name,
                default_tool_name=default_tool_name,
            )

        for leaderboard_path in self._find_leaderboard_paths(output_dir, run_summary_path, run_summary_payload):
            try:
                if leaderboard_path.suffix.lower() == ".json":
                    payload = json.loads(leaderboard_path.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(payload, list):
                        rows = [row for row in payload if isinstance(row, dict)]
                    elif isinstance(payload, dict):
                        rows = self._extract_inline_leaderboard_rows(payload)
                    else:
                        rows = []
                else:
                    with leaderboard_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                        rows = list(csv.DictReader(handle))
            except (OSError, json.JSONDecodeError, csv.Error) as exc:
                raise RuntimeError(f"Failed to read leaderboard artifact {leaderboard_path}: {exc}") from exc

            if not rows:
                raise RuntimeError(f"Leaderboard artifact {leaderboard_path} did not contain any candidate rows.")

            parsed_rows = self._parse_leaderboard_rows(
                rows,
                default_metric_name=default_metric_name,
                default_tool_name=default_tool_name,
            )
            if parsed_rows:
                return parsed_rows

        return []

    def _sort_leaderboard_entries(self, leaderboard: list[dict[str, object]]) -> list[dict[str, object]]:
        if not leaderboard:
            return []
        has_explicit_rank = any(self._coerce_int(entry.get("rank")) is not None for entry in leaderboard)
        if has_explicit_rank:
            return sorted(
                leaderboard,
                key=lambda entry: (self._coerce_int(entry.get("rank")) or 10**9, str(entry.get("model") or "")),
            )
        return sorted(
            leaderboard,
            key=lambda entry: self._coerce_float(entry.get("validation_score")) or float("-inf"),
            reverse=True,
        )

    def _validate_summary_matches_task(self, payload: dict[str, Any], task: TaskRecord | None) -> None:
        if task is None or not task.label_column:
            return

        summary_target = self._coerce_str(payload.get("target_column"))
        if summary_target is None:
            raise RuntimeError(
                "run_summary.json is missing target_column; refusing to accept an ambiguous MLZero result."
            )
        if summary_target != task.label_column:
            raise RuntimeError(
                "run_summary.json target_column does not match the task label column. "
                f"task_label_column={task.label_column!r}, run_summary_target_column={summary_target!r}"
            )

        summary_problem_type = self._coerce_str(payload.get("problem_type"))
        if task.problem_type and summary_problem_type is not None:
            normalized_summary_problem = summary_problem_type
            if normalized_summary_problem in {"binary", "multiclass"}:
                normalized_summary_problem = "classification"
            if normalized_summary_problem != task.problem_type:
                raise RuntimeError(
                    "run_summary.json problem_type does not match the task problem type. "
                    f"task_problem_type={task.problem_type!r}, run_summary_problem_type={summary_problem_type!r}"
                )

    def _build_summary(self, output_dir: Path, *, task: TaskRecord | None = None) -> RunSummary:
        candidate_errors: list[str] = []
        for run_summary_payload, run_summary_path in self._iter_run_summary_candidates(output_dir):
            try:
                return self._build_summary_from_payload(
                    output_dir,
                    run_summary_payload=run_summary_payload,
                    run_summary_path=run_summary_path,
                    task=task,
                )
            except Exception as exc:  # noqa: BLE001
                candidate_errors.append(f"{run_summary_path}: {exc}")

        if candidate_errors:
            raise RuntimeError(
                "MLZero completed but none of the run_summary.json candidates were valid. "
                + " | ".join(candidate_errors)
            )
        raise RuntimeError(f"MLZero completed but did not produce a readable run_summary.json in {output_dir}")

    def _iter_run_summary_candidates(self, output_dir: Path) -> list[tuple[dict[str, Any], Path]]:
        candidates: list[tuple[dict[str, Any], Path]] = []
        for summary_path in self._find_run_summary_paths(output_dir):
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable run_summary.json at %s: %s", summary_path, exc)
                continue
            if not isinstance(payload, dict):
                logger.warning("Skipping non-object run_summary.json at %s.", summary_path)
                continue
            candidates.append((payload, summary_path))
        return candidates

    def _build_summary_from_payload(
        self,
        output_dir: Path,
        *,
        run_summary_payload: dict[str, Any],
        run_summary_path: Path,
        task: TaskRecord | None = None,
    ) -> RunSummary:
        self._validate_summary_matches_task(run_summary_payload, task)
        best_model = self._require_summary_string(run_summary_payload, "best_model")
        metric_name = self._require_summary_string(run_summary_payload, "metric_name")
        metric_value = self._require_summary_float(run_summary_payload, "metric_value")
        validation_score = self._require_summary_float(run_summary_payload, "validation_score")
        tool_name = self._require_summary_string(run_summary_payload, "tool")
        candidate_model_count = self._require_summary_int(run_summary_payload, "candidate_model_count")
        if candidate_model_count < 1:
            raise RuntimeError("run_summary.json field 'candidate_model_count' must be at least 1.")

        leaderboard = self._load_leaderboard_entries(
            output_dir,
            run_summary_payload=run_summary_payload,
            run_summary_path=run_summary_path,
            default_metric_name=metric_name,
            default_tool_name=tool_name,
        )
        if not leaderboard:
            raise RuntimeError(
                "MLZero completed but did not persist a parsable leaderboard.json/csv or inline leaderboard list. "
                f"Output directory: {output_dir}"
            )

        leaderboard = self._sort_leaderboard_entries(leaderboard)
        for index, row in enumerate(leaderboard):
            row["rank"] = index + 1

        if len(leaderboard) < candidate_model_count:
            raise RuntimeError(
                "Leaderboard artifact contains fewer candidate rows than run_summary.json declared. "
                f"candidate_model_count={candidate_model_count}, leaderboard_rows={len(leaderboard)}"
            )

        matching_best_entry = next(
            (entry for entry in leaderboard if self._coerce_str(entry.get("model")) == best_model),
            None,
        )
        if matching_best_entry is None:
            raise RuntimeError(
                "Best model declared in run_summary.json was not found in leaderboard artifacts. "
                f"best_model={best_model!r}"
            )

        best_entry_score = self._coerce_float(matching_best_entry.get("validation_score"))
        if best_entry_score is None:
            raise RuntimeError(f"Leaderboard entry for best model {best_model!r} is missing validation_score.")
        if abs(best_entry_score - validation_score) > 1e-12:
            raise RuntimeError(
                "run_summary.json validation_score does not match the leaderboard entry for the declared best model. "
                f"run_summary={validation_score}, leaderboard={best_entry_score}"
            )

        token_usage = read_mlzero_token_usage(output_dir)
        if token_usage is None:
            raise RuntimeError(f"MLZero completed but did not persist a readable token_usage.json in {output_dir}")

        return RunSummary(
            best_model=best_model,
            metric_name=metric_name,
            metric_value=metric_value,
            validation_score=validation_score,
            leaderboard=leaderboard,
            output_dir=str(output_dir),
            token_usage=token_usage,
        )

    def build_summary_from_output(self, output_dir: Path | str) -> RunSummary:
        return self._build_summary(Path(output_dir))

    def unavailability_reason(self) -> str | None:
        provider_reason = self.provider_unavailability_reason()
        if provider_reason is not None:
            return provider_reason
        runtime_reason = self.runtime_unavailability_reason()
        if runtime_reason is not None:
            return runtime_reason
        return None

    def provider_unavailability_reason(self) -> str | None:
        return self.provider.unavailability_reason()

    def runtime_unavailability_reason(self) -> str | None:
        if not self.settings.mlzero_config_path.exists():
            return f"config file missing at {self.settings.mlzero_config_path}"
        if self.settings.mlzero_execution_mode == "mamba":
            if resolve_mamba_executable(self.settings.mlzero_mamba_executable) is None:
                return f"mamba executable not found from {self.settings.mlzero_mamba_executable}"
        else:
            python_reason = python_runtime_unavailability_reason(self.settings.mlzero_python_executable)
            if python_reason is not None:
                return python_reason
        if self.settings.mlzero_uses_local_provider and not self.settings.mlzero_model_path.exists():
            return f"local model file missing at {self.settings.mlzero_model_path}"
        return None

    def _resolve_search_plan(self, _time_limit: int | None = None) -> tuple[int, bool]:
        return max(1, self.settings.mlzero_max_iterations), self.settings.mlzero_continuous_improvement

    def _build_runtime_config(self, output_dir: Path, *, continuous_improvement: bool) -> Path:
        template = self.settings.mlzero_config_path.read_text(encoding="utf-8")
        model_value = json.dumps(self.settings.mlzero_model_alias, ensure_ascii=False)
        proxy_value = json.dumps(self.settings.mlzero_provider_base_url, ensure_ascii=False)
        wire_api_value = json.dumps(self.settings.mlzero_provider_wire_api, ensure_ascii=False)
        continuous_value = str(continuous_improvement).lower()
        mcp_web_search_enabled_value = str(bool(getattr(self.settings, "mlzero_mcp_web_search_enabled", False))).lower()
        mcp_web_search_server_url_value = json.dumps(getattr(self.settings, "mlzero_mcp_web_search_server_url", ""), ensure_ascii=False)
        mcp_web_search_tool_name_value = json.dumps(getattr(self.settings, "mlzero_mcp_web_search_tool_name", ""), ensure_ascii=False)
        mcp_web_search_top_k_value = str(max(1, int(getattr(self.settings, "mlzero_mcp_web_search_top_k", 5) or 5)))
        mcp_web_search_timeout_value = str(max(1, int(getattr(self.settings, "mlzero_mcp_web_search_timeout_seconds", 20) or 20)))

        resolved, model_count = re.subn(
            r"(^\s*model:\s*).*$",
            rf"\1{model_value}",
            template,
            count=1,
            flags=re.MULTILINE,
        )
        resolved, proxy_count = re.subn(
            r"(^\s*proxy_url:\s*).*$",
            rf"\1{proxy_value}",
            resolved,
            count=1,
            flags=re.MULTILINE,
        )
        resolved, wire_api_count = re.subn(
            r"(^\s*wire_api:\s*).*$",
            rf"\1{wire_api_value}",
            resolved,
            count=1,
            flags=re.MULTILINE,
        )
        request_timeout_value = str(max(180, self.settings.mlzero_provider_request_timeout_seconds))
        resolved, request_timeout_count = re.subn(
            r"(^\s*request_timeout:\s*).*$",
            lambda match: f"{match.group(1)}{request_timeout_value}",
            resolved,
            count=1,
            flags=re.MULTILINE,
        )
        resolved, continuous_count = re.subn(
            r"(^\s*continuous_improvement:\s*).*$",
            rf"\1{continuous_value}",
            resolved,
            count=1,
            flags=re.MULTILINE,
        )
        replacements = {
            "mcp_web_search_enabled": mcp_web_search_enabled_value,
            "mcp_web_search_server_url": mcp_web_search_server_url_value,
            "mcp_web_search_tool_name": mcp_web_search_tool_name_value,
            "mcp_web_search_top_k": mcp_web_search_top_k_value,
            "mcp_web_search_timeout_seconds": mcp_web_search_timeout_value,
        }
        replacement_counts: dict[str, int] = {}
        for key, value in replacements.items():
            resolved, replacement_counts[key] = re.subn(
                rf"(^\s*{re.escape(key)}:\s*).*$",
                lambda match, replacement=value: f"{match.group(1)}{replacement}",
                resolved,
                count=1,
                flags=re.MULTILINE,
            )
            if replacement_counts[key] == 0:
                resolved = f"{key}: {value}\n{resolved}"
                replacement_counts[key] = 1

        if (
            model_count != 1
            or proxy_count != 1
            or wire_api_count != 1
            or request_timeout_count != 1
            or continuous_count != 1
            or any(count != 1 for count in replacement_counts.values())
        ):
            raise RuntimeError(
                "Failed to materialize MLZero runtime config with the active provider settings."
            )

        runtime_config_path = output_dir / "mlzero-runtime-config.yaml"
        runtime_config_path.write_text(resolved, encoding="utf-8")
        return runtime_config_path

    def _build_command(
        self,
        input_dir: Path,
        output_dir: Path,
        runtime_config_path: Path,
        task: TaskRecord,
        *,
        max_iterations: int,
        continuous_improvement: bool,
    ) -> list[str]:
        common_args = [
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            str(runtime_config_path),
            "--provider",
            "openai",
            "-n",
            str(max_iterations),
            "--initial-instruction",
            self._build_initial_instruction(task),
        ]
        if continuous_improvement:
            common_args.append("--continuous_improvement")
        common_args.extend(["-v", "1"])

        if self.settings.mlzero_execution_mode == "mamba":
            mamba_executable = resolve_mamba_executable(self.settings.mlzero_mamba_executable)
            if mamba_executable is None:
                raise FileNotFoundError(
                    f"MLZero mamba executable not found: {self.settings.mlzero_mamba_executable}"
                )
            return [
                mamba_executable,
                "run",
                "-n",
                self.settings.mlzero_env_name,
                "mlzero",
                *common_args,
            ]

        python_executable = resolve_python_executable(self.settings.mlzero_python_executable)
        if python_executable is None:
            raise FileNotFoundError(
                f"MLZero python executable not found: {self.settings.mlzero_python_executable}"
            )

        return [
            python_executable,
            "-m",
            "autogluon.assistant.cli.app",
            *common_args,
        ]

    def _build_failure_message(self, result: subprocess.CompletedProcess[str], output_dir: Path) -> str:
        stderr_tail = self._tail_text(result.stderr, lines=30)
        stdout_tail = self._tail_text(result.stdout, lines=30)
        logs_tail = self._read_tail(output_dir / "logs.txt", lines=60)
        info_tail = self._read_tail(output_dir / "info_logs.txt", lines=60)

        parts = [
            "MLZero run failed.",
            f"Return code: {result.returncode}",
            f"Output directory: {output_dir}",
        ]
        if logs_tail:
            parts.extend(["logs.txt tail:", logs_tail])
        if info_tail and info_tail != logs_tail:
            parts.extend(["info_logs.txt tail:", info_tail])
        if stdout_tail:
            parts.extend(["Captured STDOUT tail:", stdout_tail])
        if stderr_tail:
            parts.extend(["Captured STDERR tail:", stderr_tail])
        if not logs_tail and not stdout_tail and not stderr_tail:
            parts.append("No captured stdout/stderr and no logs.txt found in output directory.")
        return "\n".join(parts)

    def _append_repair_note(self, output_dir: Path, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp} INFO     [ai4ml.runtime_repair] {message}\n"
        for name in ("logs.txt", "info_logs.txt", "detail_logs.txt", "mlzero_stdout.log"):
            try:
                with (output_dir / name).open("a", encoding="utf-8", errors="replace") as handle:
                    handle.write(line)
            except OSError:
                continue

    def _combined_failure_text(self, result: subprocess.CompletedProcess[str], output_dir: Path) -> str:
        parts = [
            result.stdout or "",
            result.stderr or "",
            self._read_tail(output_dir / "logs.txt", lines=160),
            self._read_tail(output_dir / "info_logs.txt", lines=160),
            self._read_tail(output_dir / "detail_logs.txt", lines=160),
            self._read_tail(output_dir / "mlzero_stderr.log", lines=160),
        ]
        return "\n".join(part for part in parts if part)

    def _is_transient_provider_timeout(self, result: subprocess.CompletedProcess[str], output_dir: Path) -> bool:
        text = self._combined_failure_text(result, output_dir).lower()
        return "apitimeouterror" in text or "request timed out" in text or "readtimeout" in text

    def _is_recoverable_failure(self, result: subprocess.CompletedProcess[str], output_dir: Path) -> bool:
        text = self._combined_failure_text(result, output_dir).lower()
        if any(marker in text for marker in ("apitimeouterror", "request timed out", "readtimeout", "retryerror")):
            return True
        if any(marker in text for marker in ("modulenotfounderror", "no module named", "run_summary.json", "leaderboard")):
            return True
        return False

    def _infer_retry_stage(self, result: subprocess.CompletedProcess[str], output_dir: Path) -> str | None:
        text = self._combined_failure_text(result, output_dir).lower()
        if "coderagent" in text or "python_coder" in text or "apitimeouterror" in text or "request timed out" in text:
            return "feature_engineering"
        if "fitting model" in text or "training" in text or "validation score" in text:
            return "training_validation"
        if "run_summary" in text or "leaderboard" in text:
            return "report_generation"
        if "reading file" in text or "data_perception" in text or "no module named" in text:
            return "data_analysis"
        return None

    @staticmethod
    def _tail_text(text: str, *, lines: int) -> str:
        if not text:
            return ""
        return "\n".join(text.strip().splitlines()[-lines:])

    @staticmethod
    def _read_tail(path: Path, *, lines: int) -> str:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""
        except OSError:
            return ""
        return MLZeroExecutor._tail_text(content, lines=lines)

