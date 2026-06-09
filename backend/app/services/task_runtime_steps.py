from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    TaskRecord,
    TaskStepSummaryRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.task_runtime_codex_steps import codex_steps_from_progress
from backend.app.services.task_runtime_stage_steps import workflow_steps_from_stage_records


def build_runtime_steps(
    task: TaskRecord,
    stage_records: list[object],
    progress: object | None,
) -> list[TaskStepSummaryRecord]:
    codex_steps = codex_steps_from_progress(progress)
    if codex_steps:
        return codex_steps

    steps = workflow_steps_from_stage_records(task, stage_records)
    if progress is not None:
        _apply_progress_activity(steps, progress)
        _apply_training_metric_summary(steps, progress)
    return steps


def progress_from_steps(task: TaskRecord, steps: list[TaskStepSummaryRecord]) -> dict[str, object]:
    if task.status == TaskStatus.completed:
        return _progress_from_cached_task(task)
    if task.status in {TaskStatus.failed, TaskStatus.cancelled}:
        return _non_completion_terminal_progress(task, steps)
    if _is_human_waiting_status(task.status):
        return _blocked_progress_from_steps(steps)
    if task.status in {TaskStatus.uploaded, TaskStatus.planning, TaskStatus.draft}:
        return _progress_from_cached_task(task)
    if not steps:
        return _progress_from_cached_task(task)

    current = _current_progress_step(steps)
    return {
        "status": "running" if task.status == TaskStatus.running else _enum_value(task.status),
        "progress_percent": _stage_progress_percent(steps),
        "progress_source": "stage_status",
        "progress_unavailable_reason": None,
        "current_stage": current.name if current is not None else None,
        "current_activity": current.message if current is not None else "",
    }


def _is_terminal_status(status: TaskStatus | str) -> bool:
    return status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}


def _is_human_waiting_status(status: TaskStatus | str) -> bool:
    return status in {TaskStatus.waiting_human, TaskStatus.paused_for_review}


def _blocked_progress_from_steps(steps: list[TaskStepSummaryRecord]) -> dict[str, object]:
    waiting = _step_with_status(steps, WorkflowStageStatus.waiting_human)
    return {
        "status": "blocked",
        "progress_percent": _stage_progress_percent(steps) if steps else 50,
        "progress_source": "stage_status" if steps else "status_fallback",
        "progress_unavailable_reason": None,
        "current_stage": waiting.name if waiting else WorkflowStage.training_validation.value,
        "current_activity": waiting.message if waiting else "等待人工确认",
    }


def _non_completion_terminal_progress(task: TaskRecord, steps: list[TaskStepSummaryRecord]) -> dict[str, object]:
    current = _terminal_progress_step(steps)
    return {
        "status": _enum_value(task.status),
        "progress_percent": _stage_progress_percent(steps),
        "progress_source": "stage_status" if steps else None,
        "progress_unavailable_reason": None if steps else "progress_percent_missing",
        "current_stage": current.name if current is not None else None,
        "current_activity": current.message if current is not None else "",
    }


def _current_progress_step(steps: list[TaskStepSummaryRecord]) -> TaskStepSummaryRecord | None:
    for status in (
        WorkflowStageStatus.running,
        WorkflowStageStatus.waiting_human,
        WorkflowStageStatus.pending,
    ):
        step = _step_with_status(steps, status)
        if step is not None:
            return step
    return None


def _terminal_progress_step(steps: list[TaskStepSummaryRecord]) -> TaskStepSummaryRecord | None:
    for status in (
        WorkflowStageStatus.failed,
        WorkflowStageStatus.running,
        WorkflowStageStatus.waiting_human,
        WorkflowStageStatus.pending,
    ):
        step = _step_with_status(steps, status)
        if step is not None:
            return step
    return None


def _stage_progress_percent(steps: list[TaskStepSummaryRecord]) -> int | None:
    if not steps:
        return None
    score = 0.0
    for step in steps:
        status = _enum_value(step.status)
        if status == WorkflowStageStatus.completed.value:
            score += 1.0
        elif status in {
            WorkflowStageStatus.running.value,
            WorkflowStageStatus.waiting_human.value,
            WorkflowStageStatus.failed.value,
        }:
            score += 0.5
    return min(99, max(0, round((score / len(steps)) * 100)))


def _step_with_status(
    steps: list[TaskStepSummaryRecord],
    status: WorkflowStageStatus,
) -> TaskStepSummaryRecord | None:
    return next((step for step in steps if _enum_value(step.status) == status.value), None)


def _apply_progress_activity(steps: list[TaskStepSummaryRecord], progress: object) -> None:
    current_stage = getattr(progress, "current_stage", None)
    current_stage_key = _enum_value(current_stage) if current_stage is not None else ""
    progress_status = str(getattr(progress, "status", "") or "")
    if progress_status not in {"running", "repairing", "blocked", "stale"}:
        return

    current_activity = str(getattr(progress, "current_activity", "") or getattr(progress, "observer_detail", "") or "")
    status = WorkflowStageStatus.waiting_human if progress_status == "blocked" else WorkflowStageStatus.running
    for step in steps:
        if step.name != current_stage_key:
            continue
        step.status = _enum_value(status)
        if current_activity:
            step.message = current_activity


def _apply_training_metric_summary(steps: list[TaskStepSummaryRecord], progress: object) -> None:
    artifacts = getattr(progress, "artifacts", None)
    metric_name = getattr(artifacts, "metric_name", None) if artifacts is not None else None
    if not metric_name:
        return

    for step in steps:
        if step.name != WorkflowStage.training_validation.value or step.summary:
            continue
        metric_value = getattr(artifacts, "metric_value", None)
        best_model = getattr(artifacts, "best_model", None)
        parts = [f"{metric_name}: {metric_value if metric_value is not None else '-'}"]
        if best_model:
            parts.append(f"最佳模型: {best_model}")
        step.summary = "；".join(parts)


def _progress_from_cached_task(task: TaskRecord) -> dict[str, object]:
    if task.status == TaskStatus.completed:
        return {
            "status": "completed",
            "progress_percent": 100,
            "progress_source": "status_fallback",
            "current_stage": WorkflowStage.report_generation.value,
        }
    if task.status in {TaskStatus.failed, TaskStatus.cancelled}:
        return {
            "status": _enum_value(task.status),
            "progress_percent": None,
            "progress_source": None,
            "progress_unavailable_reason": "progress_percent_missing",
            "current_stage": None,
        }
    if task.status in {TaskStatus.waiting_human, TaskStatus.paused_for_review}:
        return {
            "status": "blocked",
            "progress_percent": 50,
            "progress_source": "status_fallback",
            "progress_unavailable_reason": None,
            "current_stage": WorkflowStage.training_validation.value,
            "current_activity": "等待人工确认",
        }
    if task.status == TaskStatus.running:
        return {
            "status": "running",
            "progress_percent": 1,
            "progress_source": "status_fallback",
            "progress_unavailable_reason": None,
            "current_stage": WorkflowStage.training_validation.value,
            "current_activity": "",
        }
    if task.status in {TaskStatus.uploaded, TaskStatus.planning}:
        return {"status": "not_started", "progress_percent": 0, "current_stage": WorkflowStage.data_analysis.value}
    return {"status": "not_started", "progress_percent": 0, "current_stage": None}


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)
