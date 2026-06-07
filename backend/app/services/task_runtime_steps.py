from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskRecord,
    TaskStepSummaryRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_runtime_codex_steps import codex_steps_from_progress


STAGE_LABELS = {
    WorkflowStage.requirement_analysis: "需求解析",
    WorkflowStage.data_analysis: "数据分析",
    WorkflowStage.feature_engineering: "特征工程",
    WorkflowStage.model_selection: "模型选择",
    WorkflowStage.training_validation: "训练验证",
    WorkflowStage.report_generation: "报告生成",
}

def build_runtime_steps(
    task: TaskRecord,
    stage_records: list[object],
    progress: object | None,
) -> list[TaskStepSummaryRecord]:
    codex_steps = codex_steps_from_progress(progress)
    if codex_steps:
        return codex_steps

    steps = _workflow_steps_from_stage_records(task, stage_records)
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
        "progress_percent": None,
        "progress_source": None,
        "progress_unavailable_reason": "progress_percent_missing",
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
        "progress_percent": None,
        "progress_source": None,
        "progress_unavailable_reason": "progress_percent_missing",
        "current_stage": waiting.name if waiting else WorkflowStage.training_validation.value,
        "current_activity": waiting.message if waiting else "等待人工确认",
    }


def _non_completion_terminal_progress(task: TaskRecord, steps: list[TaskStepSummaryRecord]) -> dict[str, object]:
    current = _terminal_progress_step(steps)
    return {
        "status": _enum_value(task.status),
        "progress_percent": None,
        "progress_source": None,
        "progress_unavailable_reason": "progress_percent_missing",
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


def _step_with_status(
    steps: list[TaskStepSummaryRecord],
    status: WorkflowStageStatus,
) -> TaskStepSummaryRecord | None:
    return next((step for step in steps if _enum_value(step.status) == status.value), None)


def _workflow_steps_from_stage_records(
    task: TaskRecord,
    stage_records: list[object],
) -> list[TaskStepSummaryRecord]:
    latest_by_stage: dict[str, TaskStepSummaryRecord] = {}
    for record in stage_records:
        step = _step_from_stage_record(record)
        latest_by_stage.setdefault(step.name, step)
    return [latest_by_stage.get(stage.value) or _fallback_step(task, stage) for stage in PRIMARY_WORKFLOW_STAGES]


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


def _step_from_stage_record(record: object) -> TaskStepSummaryRecord:
    stage = normalize_workflow_stage(getattr(record, "stage", WorkflowStage.requirement_analysis))
    return TaskStepSummaryRecord(
        id=str(getattr(record, "id", "") or stage.value),
        name=stage.value,
        node=stage.value,
        title=STAGE_LABELS.get(stage, stage.value),
        agent_role=STAGE_LABELS.get(stage, stage.value),
        status=_enum_value(getattr(record, "status", WorkflowStageStatus.pending)),
        message=str(getattr(record, "summary", None) or getattr(record, "log_excerpt", None) or ""),
        summary=str(getattr(record, "summary", None) or ""),
        duration_s=getattr(record, "duration_seconds", None),
        artifacts=_flatten_artifact_refs(getattr(record, "artifact_refs", None)),
        updated_at=getattr(record, "updated_at", None),
    )


def _fallback_step(task: TaskRecord, stage: WorkflowStage) -> TaskStepSummaryRecord:
    return TaskStepSummaryRecord(
        id=stage.value,
        name=stage.value,
        node=stage.value,
        title=STAGE_LABELS.get(stage, stage.value),
        agent_role=STAGE_LABELS.get(stage, stage.value),
        status=_enum_value(_stage_status_from_task(task, stage)),
    )


def _stage_status_from_task(task: TaskRecord, stage: WorkflowStage) -> WorkflowStageStatus:
    task_status = task.status
    if task_status == TaskStatus.completed:
        return WorkflowStageStatus.completed
    if task_status == TaskStatus.failed:
        if stage in {
            WorkflowStage.feature_engineering,
            WorkflowStage.model_selection,
            WorkflowStage.training_validation,
            WorkflowStage.report_generation,
        }:
            return WorkflowStageStatus.failed
        return WorkflowStageStatus.completed
    if task_status in {TaskStatus.waiting_human, TaskStatus.paused_for_review}:
        return WorkflowStageStatus.waiting_human if stage == WorkflowStage.training_validation else WorkflowStageStatus.pending
    if task_status == TaskStatus.running:
        if stage in {
            WorkflowStage.feature_engineering,
            WorkflowStage.model_selection,
            WorkflowStage.training_validation,
        }:
            return WorkflowStageStatus.running
        if stage in {WorkflowStage.requirement_analysis, WorkflowStage.data_analysis}:
            return WorkflowStageStatus.completed
        return WorkflowStageStatus.pending
    if task_status in {TaskStatus.uploaded, TaskStatus.planning}:
        return WorkflowStageStatus.completed if stage in {WorkflowStage.requirement_analysis, WorkflowStage.data_analysis} else WorkflowStageStatus.pending
    return WorkflowStageStatus.completed if stage == WorkflowStage.requirement_analysis else WorkflowStageStatus.pending


def _progress_from_cached_task(task: TaskRecord) -> dict[str, object]:
    if task.status == TaskStatus.completed:
        return {"status": "completed", "progress_percent": 100, "current_stage": WorkflowStage.report_generation.value}
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
            "progress_percent": None,
            "progress_source": None,
            "progress_unavailable_reason": "progress_percent_missing",
            "current_stage": WorkflowStage.training_validation.value,
        }
    if task.status == TaskStatus.running:
        return {
            "status": "running",
            "progress_percent": None,
            "progress_source": None,
            "progress_unavailable_reason": "progress_percent_missing",
            "current_stage": WorkflowStage.training_validation.value,
        }
    if task.status in {TaskStatus.uploaded, TaskStatus.planning}:
        return {"status": "not_started", "progress_percent": 0, "current_stage": WorkflowStage.data_analysis.value}
    return {"status": "not_started", "progress_percent": 0, "current_stage": None}


def _flatten_artifact_refs(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return [str(value)] if str(value or "").strip() else []


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)
