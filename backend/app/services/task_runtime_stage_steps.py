from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskRecord,
    TaskStatus,
    TaskStepSummaryRecord,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)


STAGE_LABELS = {
    WorkflowStage.requirement_analysis: "需求解析",
    WorkflowStage.data_analysis: "数据分析",
    WorkflowStage.feature_engineering: "特征工程",
    WorkflowStage.model_selection: "模型选择",
    WorkflowStage.training_validation: "训练验证",
    WorkflowStage.report_generation: "报告生成",
}


def workflow_steps_from_stage_records(
    task: TaskRecord,
    stage_records: list[object],
) -> list[TaskStepSummaryRecord]:
    latest_by_stage: dict[str, TaskStepSummaryRecord] = {}
    for record in stage_records:
        step = _step_from_stage_record(record)
        latest_by_stage.setdefault(step.name, step)
    return [latest_by_stage.get(stage.value) or _fallback_step(task, stage) for stage in PRIMARY_WORKFLOW_STAGES]


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


def _flatten_artifact_refs(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return [str(value)] if str(value or "").strip() else []


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)
