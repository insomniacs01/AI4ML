from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    TaskStatus,
    TaskStepSummaryRecord,
    WorkflowStageStatus,
)


CODEX_STEP_STATUS_MAP = {
    "completed": WorkflowStageStatus.completed.value,
    "done": WorkflowStageStatus.completed.value,
    "success": WorkflowStageStatus.completed.value,
    "running": WorkflowStageStatus.running.value,
    "in_progress": WorkflowStageStatus.running.value,
    "executing": WorkflowStageStatus.running.value,
    "waiting": WorkflowStageStatus.waiting_human.value,
    "waiting_plan_approval": WorkflowStageStatus.waiting_human.value,
    "interrupted": WorkflowStageStatus.failed.value,
    "failed": WorkflowStageStatus.failed.value,
    "error": WorkflowStageStatus.failed.value,
}
WORKFLOW_STAGE_STATUS_VALUES = {item.value for item in WorkflowStageStatus}


def codex_steps_from_progress(progress: object | None) -> list[TaskStepSummaryRecord]:
    if progress is None:
        return []
    raw_steps = _raw_codex_steps(progress)
    if not isinstance(raw_steps, list):
        return []

    progress_status = str(getattr(progress, "status", "") or "")
    task_status = getattr(progress, "task_status", None)
    paused_task = _enum_value(task_status) in {TaskStatus.paused_for_review.value, TaskStatus.waiting_human.value}
    steps: list[TaskStepSummaryRecord] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            continue
        steps.append(_codex_step_from_raw(raw_step, index, progress_status=progress_status, paused_task=paused_task))
    return steps


def _raw_codex_steps(progress: object) -> object:
    raw_steps = getattr(progress, "codex_raw_steps", None)
    if raw_steps is None:
        return getattr(progress, "raw_steps", None)
    return raw_steps


def _codex_step_from_raw(
    raw_step: dict[str, Any],
    index: int,
    *,
    progress_status: str,
    paused_task: bool,
) -> TaskStepSummaryRecord:
    step_id = str(raw_step.get("id") or f"codex_step_{index}")
    detail = str(raw_step.get("detail") or raw_step.get("summary") or "")
    return TaskStepSummaryRecord(
        id=step_id,
        name=step_id,
        node=step_id,
        title=str(raw_step.get("title") or raw_step.get("id") or f"Codex step {index}"),
        agent_role="Codex",
        status=_codex_step_status(str(raw_step.get("status") or "pending"), progress_status=progress_status, paused_task=paused_task),
        message=detail,
        summary=detail,
        artifacts=_codex_step_artifacts(raw_step),
    )


def _codex_step_status(raw_status: str, *, progress_status: str, paused_task: bool) -> str:
    if raw_status == "interrupted" and (paused_task or progress_status == "blocked"):
        return WorkflowStageStatus.waiting_human.value
    return CODEX_STEP_STATUS_MAP.get(raw_status, raw_status if raw_status in WORKFLOW_STAGE_STATUS_VALUES else "pending")


def _codex_step_artifacts(raw_step: dict[str, Any]) -> list[str]:
    artifacts = raw_step.get("artifacts", [])
    return [str(item) for item in artifacts] if isinstance(artifacts, list) else []


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)
