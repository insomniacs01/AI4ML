from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import RunSummary, TaskRecord, TokenUsageReport, WorkflowStage
from backend.app.services.executors.mlzero_executor import MLZeroExecutor
from backend.app.services.mlzero_runtime import LocalOpenAIProvider, resolve_mamba_executable, resolve_python_executable
from backend.app.services.openai_compatible_provider import call_openai_compatible_provider
from backend.app.services.task_human_context import build_task_human_context_block
from backend.app.services.token_usage import read_mlzero_token_usage


STAGE_ORDER: tuple[WorkflowStage, ...] = (
    WorkflowStage.requirement_analysis,
    WorkflowStage.data_analysis,
    WorkflowStage.feature_engineering,
    WorkflowStage.model_selection,
    WorkflowStage.training_validation,
    WorkflowStage.report_generation,
)

STRICT_INCREMENTAL_STAGES = {
    WorkflowStage.feature_engineering,
    WorkflowStage.model_selection,
    WorkflowStage.training_validation,
    WorkflowStage.report_generation,
}


class IncrementalRerunPreconditionError(RuntimeError):
    """Raised before a rerun starts when required real artifacts are missing."""


class IncrementalRerunError(RuntimeError):
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


@dataclass(frozen=True)
class IncrementalRerunPlan:
    start_stage: WorkflowStage
    source_output_dir: Path
    source_generated_code: Path | None
    run_output_dir: Path
    node_dir: Path
    node_output_dir: Path
    reused_stages: list[WorkflowStage]
    rerun_stages: list[WorkflowStage]
    mode: str


@dataclass(frozen=True)
class IncrementalRerunResult:
    summary: RunSummary
    plan: IncrementalRerunPlan
    manifest_path: Path
    reused_artifacts_by_stage: dict[WorkflowStage, list[str]] = field(default_factory=dict)
    rerun_artifacts_by_stage: dict[WorkflowStage, list[str]] = field(default_factory=dict)


def is_strict_incremental_stage(stage: WorkflowStage) -> bool:
    return stage in STRICT_INCREMENTAL_STAGES


def build_incremental_rerun_plan(
    task: TaskRecord,
    *,
    settings: Settings,
    start_stage: WorkflowStage,
) -> IncrementalRerunPlan:
    if start_stage not in STRICT_INCREMENTAL_STAGES:
        raise IncrementalRerunPreconditionError(f"{start_stage.value} is not a strict incremental rerun stage.")

    source_output_dir = _resolve_source_output_dir(task)
    source_generated_code = None
    if start_stage != WorkflowStage.report_generation:
        source_generated_code = _find_latest_generated_code(source_output_dir)
        if source_generated_code is None:
            raise IncrementalRerunPreconditionError(
                "Strict incremental rerun requires an existing generated_code.py artifact. "
                f"No generated_code.py was found under {source_output_dir}."
            )

    if start_stage == WorkflowStage.report_generation:
        _require_source_summary(source_output_dir)

    stage_index = STAGE_ORDER.index(start_stage)
    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}_from_{start_stage.value}"
    run_output_dir = settings.run_output_dir / task.id / run_id
    node_dir = run_output_dir / "node_0"
    node_output_dir = node_dir / "output"
    return IncrementalRerunPlan(
        start_stage=start_stage,
        source_output_dir=source_output_dir,
        source_generated_code=source_generated_code,
        run_output_dir=run_output_dir,
        node_dir=node_dir,
        node_output_dir=node_output_dir,
        reused_stages=list(STAGE_ORDER[:stage_index]),
        rerun_stages=list(STAGE_ORDER[stage_index:]),
        mode=_mode_for_stage(start_stage),
    )


def run_task_incrementally(
    task: TaskRecord,
    dataset_path: Path,
    *,
    settings: Settings,
    start_stage: WorkflowStage,
    time_limit: int | None,
    plan: IncrementalRerunPlan | None = None,
) -> IncrementalRerunResult:
    plan = plan or build_incremental_rerun_plan(task, settings=settings, start_stage=start_stage)
    plan.run_output_dir.mkdir(parents=True, exist_ok=False)
    plan.node_dir.mkdir(parents=True, exist_ok=True)
    plan.node_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        _prepare_input_bundle(task, dataset_path, plan, settings=settings)
        provider_usage: TokenUsageReport | None = None

        if start_stage == WorkflowStage.feature_engineering:
            provider_usage = _generate_incremental_code(task, dataset_path, plan, settings=settings)
            if provider_usage is None:
                raise RuntimeError("Incremental code generation did not return provider token usage.")
            _write_token_usage(plan.run_output_dir, provider_usage, session_name="incremental_code_generation")
            _execute_generated_code(plan, settings=settings)
        elif start_stage in {WorkflowStage.model_selection, WorkflowStage.training_validation}:
            _reuse_generated_code(plan)
            _write_token_usage(plan.run_output_dir, _zero_token_usage(), session_name="incremental_code_reuse")
            _execute_generated_code(plan, settings=settings)
        elif start_stage == WorkflowStage.report_generation:
            _rebuild_report_snapshot(task, plan)
            _write_token_usage(plan.run_output_dir, _zero_token_usage(), session_name="incremental_report_rebuild")
        else:
            raise IncrementalRerunPreconditionError(f"Unsupported incremental rerun stage: {start_stage.value}")

        _promote_node_outputs(plan)
        _copy_best_run_snapshot(plan)
        manifest_path = _write_manifest(task, plan, status="completed")
        summary = MLZeroExecutor(settings).build_summary_from_output(plan.run_output_dir)
        return IncrementalRerunResult(
            summary=summary,
            plan=plan,
            manifest_path=manifest_path,
            reused_artifacts_by_stage=_build_reused_artifact_map(plan),
            rerun_artifacts_by_stage=_build_rerun_artifact_map(plan),
        )
    except IncrementalRerunPreconditionError:
        raise
    except Exception as exc:  # noqa: BLE001
        _write_manifest(task, plan, status="failed", error=str(exc))
        raise IncrementalRerunError(
            f"Strict incremental rerun from {start_stage.value} failed: {exc}",
            output_dir=plan.run_output_dir,
            recoverable=True,
            retry_stage=start_stage.value,
        ) from exc


def _resolve_source_output_dir(task: TaskRecord) -> Path:
    candidates: list[str] = []
    if task.last_run_attempt and task.last_run_attempt.output_dir:
        candidates.append(task.last_run_attempt.output_dir)
    if task.last_run and task.last_run.output_dir:
        candidates.append(task.last_run.output_dir)

    for raw_path in candidates:
        path = Path(raw_path)
        if path.exists() and path.is_dir():
            return path

    if candidates:
        raise IncrementalRerunPreconditionError(
            "Strict incremental rerun requires the previous MLZero output directory to exist. "
            f"Checked: {', '.join(candidates)}."
        )
    raise IncrementalRerunPreconditionError(
        "Strict incremental rerun requires a previous MLZero run or run attempt with real artifacts."
    )


def _safe_path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _find_latest_generated_code(output_dir: Path) -> Path | None:
    candidates = sorted(
        (
            path
            for path in output_dir.rglob("generated_code.py")
            if path.is_file() and "best_run" not in path.parts
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _find_summary_paths(output_dir: Path) -> list[Path]:
    candidates = [
        output_dir / "best_run" / "output" / "run_summary.json",
        output_dir / "run_summary.json",
        *output_dir.glob("node_*/output/run_summary.json"),
    ]
    existing = [path for path in candidates if path.exists() and path.is_file()]
    return sorted(existing, key=lambda path: (_safe_path_mtime(path), str(path)), reverse=True)


def _require_source_summary(output_dir: Path) -> Path:
    paths = _find_summary_paths(output_dir)
    if not paths:
        raise IncrementalRerunPreconditionError(
            "Report-stage incremental rerun requires an existing run_summary.json artifact. "
            f"No run_summary.json was found under {output_dir}."
        )
    summary_path = paths[0]
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncrementalRerunPreconditionError(f"Existing run_summary.json is not readable: {summary_path}") from exc
    if not isinstance(payload, dict):
        raise IncrementalRerunPreconditionError(f"Existing run_summary.json must contain a JSON object: {summary_path}")

    inline_leaderboard = payload.get("leaderboard")
    if isinstance(inline_leaderboard, list) and inline_leaderboard:
        return summary_path

    leaderboard_candidates = [
        summary_path.parent / "leaderboard.json",
        summary_path.parent / "leaderboard.csv",
        output_dir / "leaderboard.json",
        output_dir / "leaderboard.csv",
        output_dir / "best_run" / "output" / "leaderboard.json",
        output_dir / "best_run" / "output" / "leaderboard.csv",
    ]
    if any(path.exists() and path.is_file() for path in leaderboard_candidates):
        return summary_path

    raise IncrementalRerunPreconditionError(
        "Report-stage incremental rerun requires an existing leaderboard artifact "
        f"beside {summary_path} or inline in run_summary.json."
    )


def _mode_for_stage(stage: WorkflowStage) -> str:
    if stage == WorkflowStage.feature_engineering:
        return "incremental_code_generation_and_execution"
    if stage in {WorkflowStage.model_selection, WorkflowStage.training_validation}:
        return "incremental_existing_code_execution"
    if stage == WorkflowStage.report_generation:
        return "incremental_report_rebuild"
    return "unsupported"


def _prepare_input_bundle(
    task: TaskRecord,
    dataset_path: Path,
    plan: IncrementalRerunPlan,
    *,
    settings: Settings,
) -> None:
    input_dir = plan.run_output_dir / "input"
    MLZeroExecutor(settings)._prepare_input_bundle(task, dataset_path, input_dir)


def _generate_incremental_code(
    task: TaskRecord,
    dataset_path: Path,
    plan: IncrementalRerunPlan,
    *,
    settings: Settings,
) -> TokenUsageReport | None:
    provider = LocalOpenAIProvider(settings)
    provider.ensure_running()

    previous_code = plan.source_generated_code.read_text(encoding="utf-8", errors="replace") if plan.source_generated_code else ""
    prompt = _build_incremental_codegen_prompt(
        task,
        dataset_path,
        plan,
        previous_code=previous_code,
    )
    states_dir = plan.node_dir / "states"
    states_dir.mkdir(parents=True, exist_ok=True)
    (states_dir / "incremental_python_coder_prompt.txt").write_text(prompt, encoding="utf-8")
    provider_result = call_openai_compatible_provider(
        prompt=prompt,
        settings=settings,
        system_message=(
            "You are an AutoML code generator inside AI4ML. "
            "Return one complete Python script only. Do not claim execution."
        ),
        temperature=0,
        max_tokens=6000,
    )
    if provider_result.token_usage is None:
        raise RuntimeError("AI Provider response did not include usage token data for incremental code generation.")

    (states_dir / "incremental_python_coder_response.txt").write_text(provider_result.text, encoding="utf-8")
    code = _extract_python_code(provider_result.text)
    code = _rewrite_source_paths(code, plan)
    _validate_python_code(code)
    _write_generated_code_and_runner(code, plan)
    return provider_result.token_usage


def _build_incremental_codegen_prompt(
    task: TaskRecord,
    dataset_path: Path,
    plan: IncrementalRerunPlan,
    *,
    previous_code: str,
) -> str:
    analysis = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    metric_name = analysis.get("metric_name") if isinstance(analysis.get("metric_name"), str) else None
    reasoning = analysis.get("reasoning") if isinstance(analysis.get("reasoning"), str) else None
    column_names, preview_rows = _read_dataset_preview(dataset_path)
    return (
        "Generate a complete Python training script for a strict incremental rerun starting at feature_engineering.\n"
        "Do not run task requirement analysis, data analysis, tool selection, or any MCTS search. "
        "Only generate executable feature/training code for the already analyzed task.\n"
        "Hard requirements:\n"
        f"- Read train.csv from this exact input folder: {plan.run_output_dir / 'input'}\n"
        f"- Save every output artifact under this exact output folder: {plan.node_output_dir}\n"
        "- Persist run_summary.json with keys best_model, metric_name, metric_value, validation_score, tool, candidate_model_count.\n"
        "- Persist leaderboard.json or leaderboard.csv with model and validation_score fields.\n"
        "- Use real CSV contents only; do not fabricate rows, metrics, models, or files.\n"
        "- For tabular classification/regression, prefer autogluon.tabular if available and compare multiple candidates when possible.\n"
        "- If execution cannot satisfy the task with the available data, raise an exception instead of writing fake success artifacts.\n"
        "- Return one complete Python script in one python code block.\n\n"
        "Task context:\n"
        f"- Task name: {task.name}\n"
        f"- Task description: {task.description}\n"
        f"- Label column: {task.label_column or 'N/A'}\n"
        f"- Problem type: {task.problem_type or 'N/A'}\n"
        f"- Metric: {metric_name or 'N/A'}\n"
        f"- AI analysis notes: {reasoning or 'N/A'}\n"
        f"- CSV columns: {json.dumps(column_names, ensure_ascii=False)}\n"
        f"- CSV preview rows: {json.dumps(preview_rows, ensure_ascii=False, indent=2)}\n\n"
        "Human collaboration decisions to apply:\n"
        f"{build_task_human_context_block(task)}\n\n"
        "Previous generated_code.py is provided only as a reference. Improve or replace it as needed, "
        "but keep the new script self-contained and use the new paths above:\n"
        f"```python\n{_clip_text(previous_code, 30000)}\n```\n"
    )


def _read_dataset_preview(dataset_path: Path, *, max_rows: int = 5) -> tuple[list[str], list[dict[str, str]]]:
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return [], []
        rows: list[dict[str, str]] = []
        for index, row in enumerate(reader):
            if index >= max_rows:
                break
            rows.append({str(key): ("" if value is None else str(value))[:120] for key, value in row.items()})
    return [str(item) for item in reader.fieldnames], rows


def _extract_python_code(response_text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", response_text, flags=re.IGNORECASE | re.DOTALL)
    code = match.group(1) if match else response_text
    code = code.strip()
    if not code:
        raise RuntimeError("Incremental code generation returned an empty script.")
    if "```" in code:
        raise RuntimeError("Incremental code generation returned nested markdown fences instead of raw Python.")
    return code


def _validate_python_code(code: str) -> None:
    try:
        compile(code, "generated_code.py", "exec")
    except SyntaxError as exc:
        raise RuntimeError(f"Incremental generated_code.py is not valid Python: {exc}") from exc


def _reuse_generated_code(plan: IncrementalRerunPlan) -> None:
    if plan.source_generated_code is None:
        raise IncrementalRerunPreconditionError("No generated_code.py artifact is available to reuse.")
    source_code = plan.source_generated_code.read_text(encoding="utf-8", errors="replace")
    code = _rewrite_source_paths(source_code, plan)
    _validate_python_code(code)
    _write_generated_code_and_runner(code, plan)

    source_states = plan.source_generated_code.parent / "states"
    if source_states.exists() and source_states.is_dir():
        target_states = plan.node_dir / "states"
        shutil.copytree(source_states, target_states, dirs_exist_ok=True)
    (plan.node_dir / "states").mkdir(parents=True, exist_ok=True)
    (plan.node_dir / "states" / "incremental_reuse_source.txt").write_text(
        str(plan.source_generated_code),
        encoding="utf-8",
    )


def _rewrite_source_paths(code: str, plan: IncrementalRerunPlan) -> str:
    replacements: list[tuple[Path, Path]] = []
    if plan.source_generated_code is not None:
        replacements.extend(
            [
                (plan.source_generated_code.parent / "output", plan.node_output_dir),
                (plan.source_generated_code.parent, plan.node_dir),
            ]
        )
    replacements.extend(
        [
            (plan.source_output_dir / "input", plan.run_output_dir / "input"),
            (plan.source_output_dir, plan.run_output_dir),
        ]
    )

    rewritten = code
    for source_path, target_path in replacements:
        rewritten = _replace_path_variants(rewritten, source_path, target_path)
    return rewritten


def _replace_path_variants(text: str, source_path: Path, target_path: Path) -> str:
    source = str(source_path)
    target = str(target_path)
    variants = {
        (source, target),
        (source.replace("\\", "\\\\"), target.replace("\\", "\\\\")),
        (source_path.as_posix(), target_path.as_posix()),
    }
    result = text
    for old, new in sorted(variants, key=lambda item: len(item[0]), reverse=True):
        result = result.replace(old, new)
    return result


def _write_generated_code_and_runner(code: str, plan: IncrementalRerunPlan) -> None:
    plan.node_dir.mkdir(parents=True, exist_ok=True)
    plan.node_output_dir.mkdir(parents=True, exist_ok=True)
    code_path = plan.node_dir / "generated_code.py"
    code_path.write_text(code, encoding="utf-8")

    if os.name == "nt":
        runner = "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                f'Set-Location "{plan.node_dir}"',
                'python "generated_code.py"',
                "",
            ]
        )
    else:
        runner = "#!/usr/bin/env bash\nset -euo pipefail\ncd \"$(dirname \"$0\")\"\npython generated_code.py\n"
    (plan.node_dir / "execution_script.sh").write_text(runner, encoding="utf-8")


def _execute_generated_code(plan: IncrementalRerunPlan, *, settings: Settings) -> None:
    command = _build_python_execution_command(settings, plan.node_dir / "generated_code.py")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        result = subprocess.run(  # noqa: S603
            command,
            cwd=str(plan.node_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _write_execution_streams(plan, exc.stdout or "", exc.stderr or "")
        raise RuntimeError("Incremental generated_code.py timed out.") from exc

    _write_execution_streams(plan, result.stdout or "", result.stderr or "")
    if result.returncode != 0:
        stderr_tail = _tail_text(result.stderr or "", lines=30)
        stdout_tail = _tail_text(result.stdout or "", lines=30)
        raise RuntimeError(
            "Incremental generated_code.py failed. "
            f"Return code: {result.returncode}. "
            f"STDOUT tail: {stdout_tail or '<empty>'}. "
            f"STDERR tail: {stderr_tail or '<empty>'}."
        )

    if not _find_summary_paths(plan.run_output_dir):
        raise RuntimeError(
            "Incremental generated_code.py completed but did not produce run_summary.json "
            f"under {plan.run_output_dir}."
        )


def _build_python_execution_command(settings: Settings, code_path: Path) -> list[str]:
    if settings.mlzero_execution_mode == "mamba":
        mamba_executable = resolve_mamba_executable(settings.mlzero_mamba_executable)
        if mamba_executable is None:
            raise FileNotFoundError(f"MLZero mamba executable not found: {settings.mlzero_mamba_executable}")
        return [
            mamba_executable,
            "run",
            "-n",
            settings.mlzero_env_name,
            "python",
            str(code_path),
        ]

    python_executable = resolve_python_executable(settings.mlzero_python_executable)
    if python_executable is None:
        raise FileNotFoundError(f"MLZero python executable not found: {settings.mlzero_python_executable}")
    return [python_executable, str(code_path)]


def _write_execution_streams(plan: IncrementalRerunPlan, stdout: str, stderr: str) -> None:
    (plan.run_output_dir / "mlzero_stdout.log").write_text(stdout, encoding="utf-8")
    (plan.run_output_dir / "mlzero_stderr.log").write_text(stderr, encoding="utf-8")
    states_dir = plan.node_dir / "states"
    states_dir.mkdir(parents=True, exist_ok=True)
    (states_dir / "stdout").write_text(stdout, encoding="utf-8")
    (states_dir / "stderr").write_text(stderr, encoding="utf-8")


def _rebuild_report_snapshot(task: TaskRecord, plan: IncrementalRerunPlan) -> None:
    source_summary_path = _require_source_summary(plan.source_output_dir)
    source_summary_payload = json.loads(source_summary_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(source_summary_payload, dict):
        raise RuntimeError(f"Source run_summary.json at {source_summary_path} must contain a JSON object.")

    _copy_source_result_artifacts(source_summary_path.parent, plan.run_output_dir)
    generated_code = _find_latest_generated_code(plan.source_output_dir)
    if generated_code is not None:
        _reuse_generated_code_for_report(plan, generated_code)

    report_lines = [
        f"# Incremental report snapshot for {task.name}",
        "",
        f"- Source output directory: {plan.source_output_dir}",
        f"- Rebuilt at: {datetime.now(timezone.utc).isoformat()}",
        f"- Best model: {source_summary_payload.get('best_model')}",
        f"- Metric: {source_summary_payload.get('metric_name')} = {source_summary_payload.get('metric_value')}",
        f"- Search score: {source_summary_payload.get('validation_score')}",
        "",
        "This report-stage rerun reused the prior model/training artifacts and rebuilt report metadata only.",
    ]
    (plan.run_output_dir / "report_snapshot.md").write_text("\n".join(report_lines), encoding="utf-8")
    (plan.node_output_dir / "report_snapshot.md").write_text("\n".join(report_lines), encoding="utf-8")


def _copy_source_result_artifacts(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("run_summary.json", "leaderboard.json", "leaderboard.csv", "summary.txt"):
        source = source_dir / name
        if source.exists() and source.is_file():
            shutil.copy2(source, target_dir / name)
            shutil.copy2(source, target_dir / "node_0" / "output" / name)


def _reuse_generated_code_for_report(plan: IncrementalRerunPlan, generated_code: Path) -> None:
    plan.node_dir.mkdir(parents=True, exist_ok=True)
    code = generated_code.read_text(encoding="utf-8", errors="replace")
    code = _rewrite_source_paths(code, IncrementalRerunPlan(
        start_stage=plan.start_stage,
        source_output_dir=plan.source_output_dir,
        source_generated_code=generated_code,
        run_output_dir=plan.run_output_dir,
        node_dir=plan.node_dir,
        node_output_dir=plan.node_output_dir,
        reused_stages=plan.reused_stages,
        rerun_stages=plan.rerun_stages,
        mode=plan.mode,
    ))
    (plan.node_dir / "generated_code.py").write_text(code, encoding="utf-8")


def _promote_node_outputs(plan: IncrementalRerunPlan) -> None:
    summary_paths = _find_summary_paths(plan.run_output_dir)
    if not summary_paths:
        return
    source_dir = summary_paths[0].parent
    if source_dir.resolve() == plan.run_output_dir.resolve():
        return
    for item in source_dir.iterdir():
        target = plan.run_output_dir / item.name
        if item.is_file():
            shutil.copy2(item, target)
        elif item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)


def _copy_best_run_snapshot(plan: IncrementalRerunPlan) -> None:
    best_run = plan.run_output_dir / "best_run"
    if best_run.exists():
        shutil.rmtree(best_run)
    if plan.node_dir.exists():
        shutil.copytree(plan.node_dir, best_run, dirs_exist_ok=True)


def _write_manifest(
    task: TaskRecord,
    plan: IncrementalRerunPlan,
    *,
    status: str,
    error: str | None = None,
) -> Path:
    manifest = {
        "strict_incremental": True,
        "status": status,
        "task_id": task.id,
        "start_stage": plan.start_stage.value,
        "mode": plan.mode,
        "source_output_dir": str(plan.source_output_dir),
        "run_output_dir": str(plan.run_output_dir),
        "reused_stages": [stage.value for stage in plan.reused_stages],
        "rerun_stages": [stage.value for stage in plan.rerun_stages],
        "source_generated_code": str(plan.source_generated_code) if plan.source_generated_code else None,
        "generated_code": str(plan.node_dir / "generated_code.py") if (plan.node_dir / "generated_code.py").exists() else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
    manifest_path = plan.run_output_dir / "incremental_rerun_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _build_reused_artifact_map(plan: IncrementalRerunPlan) -> dict[WorkflowStage, list[str]]:
    refs = [str(plan.source_output_dir), str(plan.run_output_dir / "incremental_rerun_manifest.json")]
    return {stage: refs for stage in plan.reused_stages}


def _build_rerun_artifact_map(plan: IncrementalRerunPlan) -> dict[WorkflowStage, list[str]]:
    refs = [str(plan.run_output_dir), str(plan.run_output_dir / "incremental_rerun_manifest.json")]
    return {stage: refs for stage in plan.rerun_stages}


def _write_token_usage(output_dir: Path, usage: TokenUsageReport, *, session_name: str) -> None:
    payload = {
        "total": {
            "total_input_tokens": usage.input_tokens,
            "total_output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
        "sessions": {
            session_name: {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            }
        },
        "conversations": {},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "token_usage.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _zero_token_usage() -> TokenUsageReport:
    return TokenUsageReport(input_tokens=0, output_tokens=0, total_tokens=0, sessions=[], conversations=[])


def _tail_text(text: str, *, lines: int) -> str:
    if not text:
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])


def _clip_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]..."
