from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    RunSummary,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_human_context import get_task_human_loop


STAGE_ORDER = list(PRIMARY_WORKFLOW_STAGES)


@dataclass(frozen=True)
class StageBlueprint:
    stage: WorkflowStage
    status: WorkflowStageStatus
    summary: str


def build_stage_blueprints(task: TaskRecord) -> list[StageBlueprint]:
    effective_status = get_progress_status(task)

    return apply_rerun_stage_hint(
        task,
        [
            requirement_stage_blueprint(task),
            data_analysis_stage_blueprint(task, effective_status),
            feature_engineering_stage_blueprint(task, effective_status),
            model_selection_stage_blueprint(task, effective_status),
            training_validation_stage_blueprint(task, effective_status),
            report_generation_stage_blueprint(task, effective_status),
        ],
    )


def requirement_stage_blueprint(task: TaskRecord) -> StageBlueprint:
    status = WorkflowStageStatus.completed if task.dataset_filename else WorkflowStageStatus.pending
    summary = (
        "Task description and dataset are available for the next steps."
        if task.dataset_filename
        else "Waiting for task creation details and CSV upload."
    )
    return StageBlueprint(WorkflowStage.requirement_analysis, status, summary)


def data_analysis_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    if task.label_column and task.problem_type:
        return StageBlueprint(
            WorkflowStage.data_analysis,
            WorkflowStageStatus.completed,
            f"Detected label column '{task.label_column}' and task type '{task.problem_type}'.",
        )
    if task.dataset_filename:
        status = (
            WorkflowStageStatus.running
            if effective_status in {TaskStatus.planning, TaskStatus.uploaded}
            else WorkflowStageStatus.pending
        )
        return StageBlueprint(
            WorkflowStage.data_analysis,
            status,
            "Dataset is uploaded. Waiting for AI analysis to infer label column, problem type, and metric.",
        )
    return StageBlueprint(
        WorkflowStage.data_analysis,
        WorkflowStageStatus.pending,
        "No dataset is available for AI data analysis yet.",
    )


def feature_engineering_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    return StageBlueprint(
        WorkflowStage.feature_engineering,
        build_generation_stage_status(task, effective_status),
        build_generation_stage_summary(
            task,
            effective_status,
            pending_summary="Feature engineering has not started yet.",
            completed_summary="A recent Codex attempt already produced code and intermediate artifacts.",
        ),
    )


def model_selection_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    return StageBlueprint(
        WorkflowStage.model_selection,
        build_generation_stage_status(task, effective_status),
        build_generation_stage_summary(
            task,
            effective_status,
            pending_summary="Model selection has not started yet.",
            completed_summary="A recent Codex attempt already explored at least one model candidate.",
        ),
    )


def training_validation_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    if effective_status == TaskStatus.running:
        return StageBlueprint(
            WorkflowStage.training_validation,
            WorkflowStageStatus.running,
            "Codex is training and validating candidate models.",
        )
    if effective_status == TaskStatus.failed and task.last_run_attempt:
        return StageBlueprint(
            WorkflowStage.training_validation,
            WorkflowStageStatus.failed,
            task.notes or "The latest training or validation attempt failed.",
        )
    if task.last_run:
        return _completed_training_blueprint(task.last_run)
    return StageBlueprint(
        WorkflowStage.training_validation,
        WorkflowStageStatus.pending,
        "Training and validation have not started yet.",
    )


def _completed_training_blueprint(last_run: RunSummary) -> StageBlueprint:
    metric_label = last_run.metric_name or "validation_score"
    return StageBlueprint(
        WorkflowStage.training_validation,
        WorkflowStageStatus.completed,
        f"The latest run completed with {metric_label} = {last_run.metric_value}.",
    )


def report_generation_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    if task.status == TaskStatus.published:
        return StageBlueprint(
            WorkflowStage.report_generation,
            WorkflowStageStatus.completed,
            "The latest report has already been published.",
        )
    if task.last_run:
        status = (
            WorkflowStageStatus.completed
            if effective_status == TaskStatus.completed
            else WorkflowStageStatus.pending
        )
        return StageBlueprint(
            WorkflowStage.report_generation,
            status,
            f"The latest report is ready for review. Best model: {task.last_run.best_model}.",
        )
    if task.last_run_attempt:
        return StageBlueprint(
            WorkflowStage.report_generation,
            WorkflowStageStatus.pending,
            "Artifacts exist from the latest attempt, but a final report is not ready yet.",
        )
    return StageBlueprint(
        WorkflowStage.report_generation,
        WorkflowStageStatus.pending,
        "Report generation has not started yet.",
    )


def apply_rerun_stage_hint(task: TaskRecord, blueprints: list[StageBlueprint]) -> list[StageBlueprint]:
    human_loop = get_task_human_loop(task)
    if not human_loop.get("rerun_requested"):
        return blueprints
    raw_stage = human_loop.get("rerun_from_stage")
    if not isinstance(raw_stage, str) or not raw_stage:
        return blueprints
    try:
        rerun_stage = normalize_workflow_stage(raw_stage)
    except ValueError:
        return blueprints
    order_index = {stage.value: index for index, stage in enumerate(STAGE_ORDER)}
    rerun_index = order_index.get(rerun_stage.value)
    if rerun_index is None:
        return blueprints

    reason = human_loop.get("rerun_reason")
    next_blueprints: list[StageBlueprint] = []
    for blueprint in blueprints:
        current_index = order_index.get(blueprint.stage.value, len(order_index))
        if current_index < rerun_index:
            next_blueprints.append(blueprint)
            continue
        next_blueprints.append(
            StageBlueprint(
                stage=blueprint.stage,
                status=WorkflowStageStatus.pending,
                summary=rerun_stage_summary(blueprint.stage, reason),
            )
        )
    return next_blueprints


def rerun_stage_summary(stage: WorkflowStage, reason: object) -> str:
    summary = f"人工协同要求从“{stage.value}”所在链路重新运行。"
    if isinstance(reason, str) and reason:
        return summary + f"原因：{reason}"
    return summary


def get_progress_status(task: TaskRecord) -> TaskStatus:
    if task.status not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return task.status
    return get_previous_status(task)


def get_previous_status(task: TaskRecord) -> TaskStatus:
    human_loop = get_task_human_loop(task)
    if human_loop.get("rerun_requested"):
        return TaskStatus.uploaded if task.dataset_filename else TaskStatus.draft
    raw_status = human_loop.get("previous_status") if human_loop else None
    if isinstance(raw_status, str):
        try:
            parsed = TaskStatus(raw_status)
        except ValueError:
            parsed = None
        if parsed is not None and parsed not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            return parsed
    if task.last_run:
        return TaskStatus.completed
    if task.last_run_attempt:
        return TaskStatus.failed
    if task.label_column and task.problem_type:
        return TaskStatus.planning
    if task.dataset_filename:
        return TaskStatus.uploaded
    return TaskStatus.draft


def build_generation_stage_status(task: TaskRecord, effective_status: TaskStatus) -> WorkflowStageStatus:
    if effective_status == TaskStatus.running:
        return WorkflowStageStatus.running
    if task.last_run or task.last_run_attempt:
        return WorkflowStageStatus.completed
    return WorkflowStageStatus.pending


def build_generation_stage_summary(
    task: TaskRecord,
    effective_status: TaskStatus,
    *,
    pending_summary: str,
    completed_summary: str,
) -> str:
    if effective_status == TaskStatus.running:
        return "Codex is actively generating or refining training logic."
    if task.last_run or task.last_run_attempt:
        return completed_summary
    return pending_summary
