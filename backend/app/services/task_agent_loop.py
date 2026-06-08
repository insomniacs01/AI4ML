from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_agent_baseline import compute_baseline as _compute_baseline, pending_baseline as _baseline_pending
from backend.app.services.task_agent_baseline_metrics import baseline_completed as _baseline_completed
from backend.app.services.task_agent_checklist import build_checklist as _build_checklist
from backend.app.services.task_agent_quality import (
    build_quality_gates as _build_quality_gates,
)
from backend.app.services.task_agent_improvement import build_next_improvement as _build_next_improvement
from backend.app.services.task_agent_tuning import (
    build_stop_conditions as _build_stop_conditions,
    merge_baseline_attempt as _merge_baseline_attempt,
    merge_improvement_suggestion as _merge_improvement_suggestion,
    merge_run_attempt as _merge_run_attempt,
    merge_run_failure_attempt as _merge_run_failure_attempt,
    normalize_attempts as _normalize_attempts,
)
from backend.app.services.task_agent_workflow import build_workflow as _build_workflow


def initialize_agent_loop_for_upload(task: TaskRecord) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    loop["checklist"] = _build_checklist(task)
    loop["baseline"] = _baseline_pending("等待 AI 或人工确认目标列和问题类型后计算简单对照。")
    loop["quality_gates"] = _build_quality_gates(task, loop["baseline"])
    loop["tuning_attempts"] = _normalize_attempts(loop.get("tuning_attempts"))
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def refresh_agent_loop_after_analysis(task: TaskRecord) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    loop["checklist"] = _build_checklist(task)
    loop["baseline"] = _compute_baseline(task)
    loop["quality_gates"] = _build_quality_gates(task, loop["baseline"])
    loop["tuning_attempts"] = _merge_baseline_attempt(_normalize_attempts(loop.get("tuning_attempts")), loop["baseline"])
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def refresh_agent_loop_after_run(task: TaskRecord) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    baseline = loop.get("baseline")
    if not _baseline_completed(baseline):
        baseline = _compute_baseline(task)
    loop["checklist"] = _build_checklist(task)
    loop["baseline"] = baseline
    attempts = _merge_baseline_attempt(_normalize_attempts(loop.get("tuning_attempts")), baseline)
    attempts = _merge_run_attempt(attempts, task, baseline)
    loop["quality_gates"] = _build_quality_gates(task, baseline)
    loop["tuning_attempts"] = _merge_improvement_suggestion(attempts, task, loop["quality_gates"])
    loop["next_improvement"] = _build_next_improvement(task, loop["quality_gates"])
    loop["stop_conditions"] = _build_stop_conditions(loop["tuning_attempts"])
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def refresh_agent_loop_after_run_failure(
    task: TaskRecord,
    *,
    error_summary: str | None = None,
    output_dir: str | None = None,
) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    baseline = loop.get("baseline")
    if not _baseline_completed(baseline):
        baseline = _compute_baseline(task)
    attempts = _merge_baseline_attempt(_normalize_attempts(loop.get("tuning_attempts")), baseline)
    loop["baseline"] = baseline
    loop["checklist"] = _build_checklist(task)
    loop["tuning_attempts"] = _merge_run_failure_attempt(
        attempts,
        task,
        baseline,
        error_summary=error_summary,
        output_dir=output_dir,
    )
    loop["quality_gates"] = _build_quality_gates(task, baseline, failure_note=error_summary)
    loop["next_improvement"] = _build_next_improvement(task, loop["quality_gates"])
    loop["stop_conditions"] = _build_stop_conditions(loop["tuning_attempts"])
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def _requirements(task: TaskRecord) -> dict[str, Any]:
    return dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}


def _base_loop(task: TaskRecord) -> dict[str, Any]:
    existing = _requirements(task).get("agent_loop")
    loop = dict(existing) if isinstance(existing, dict) else {}
    loop.setdefault("version", 1)
    loop.setdefault("tuning_attempts", [])
    loop.setdefault("stop_conditions", _build_stop_conditions(loop.get("tuning_attempts")))
    loop["task_id"] = task.id
    return loop


def _stamp_loop(loop: dict[str, Any]) -> dict[str, Any]:
    loop["version"] = 1
    loop["updated_at"] = _now_iso()
    return loop


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
