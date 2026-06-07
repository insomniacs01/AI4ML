from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus, WorkflowStage, WorkflowStageStatus
from backend.app.services.task_human_stage_blueprints import StageBlueprint
from backend.app.services.task_human_stages import HumanStageSnapshotBuilder


def _task(status: TaskStatus = TaskStatus.uploaded) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-human-stages",
        team_id="team-1",
        created_by="user-1",
        name="Human Stages Task",
        description="Build stage blueprints.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _blueprint_map(task: TaskRecord) -> dict[WorkflowStage, StageBlueprint]:
    return {item.stage: item for item in HumanStageSnapshotBuilder().build_stage_blueprints(task)}


def test_stage_blueprints_for_uploaded_dataset_wait_for_data_analysis() -> None:
    task = _task(TaskStatus.uploaded)
    task.dataset_filename = "train.csv"

    by_stage = _blueprint_map(task)

    assert by_stage[WorkflowStage.requirement_analysis].status == WorkflowStageStatus.completed
    assert by_stage[WorkflowStage.requirement_analysis].summary == "Task description and dataset are available for the next steps."
    assert by_stage[WorkflowStage.data_analysis].status == WorkflowStageStatus.running
    assert by_stage[WorkflowStage.data_analysis].summary == "Dataset is uploaded. Waiting for AI analysis to infer label column, problem type, and metric."
    assert by_stage[WorkflowStage.feature_engineering].status == WorkflowStageStatus.pending
    assert by_stage[WorkflowStage.model_selection].status == WorkflowStageStatus.pending
    assert by_stage[WorkflowStage.training_validation].status == WorkflowStageStatus.pending
    assert by_stage[WorkflowStage.report_generation].status == WorkflowStageStatus.pending


def test_stage_blueprints_for_failed_attempt_preserve_failure_summary() -> None:
    task = _task(TaskStatus.failed)
    task.dataset_filename = "train.csv"
    task.label_column = "target"
    task.problem_type = "regression"
    task.last_run_attempt = RunAttempt(output_dir="workspace")
    task.notes = "Training crashed."

    by_stage = _blueprint_map(task)

    assert by_stage[WorkflowStage.data_analysis].status == WorkflowStageStatus.completed
    assert by_stage[WorkflowStage.feature_engineering].status == WorkflowStageStatus.completed
    assert by_stage[WorkflowStage.model_selection].summary == "A recent Codex attempt already explored at least one model candidate."
    assert by_stage[WorkflowStage.training_validation].status == WorkflowStageStatus.failed
    assert by_stage[WorkflowStage.training_validation].summary == "Training crashed."
    assert by_stage[WorkflowStage.report_generation].summary == "Artifacts exist from the latest attempt, but a final report is not ready yet."


def test_stage_blueprints_for_published_run_mark_report_completed() -> None:
    task = _task(TaskStatus.published)
    task.dataset_filename = "train.csv"
    task.label_column = "target"
    task.problem_type = "classification"
    task.last_run = RunSummary(
        best_model="LightGBM",
        metric_name="accuracy",
        metric_value=0.91,
        output_dir="workspace",
    )

    by_stage = _blueprint_map(task)

    assert by_stage[WorkflowStage.training_validation].status == WorkflowStageStatus.completed
    assert by_stage[WorkflowStage.training_validation].summary == "The latest run completed with accuracy = 0.91."
    assert by_stage[WorkflowStage.report_generation].status == WorkflowStageStatus.completed
    assert by_stage[WorkflowStage.report_generation].summary == "The latest report has already been published."


def test_stage_blueprints_apply_rerun_hint_from_requested_stage() -> None:
    task = _task(TaskStatus.completed)
    task.dataset_filename = "train.csv"
    task.label_column = "target"
    task.problem_type = "regression"
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir="workspace",
    )
    task.structured_requirements = {
        "human_loop": {
            "rerun_requested": True,
            "rerun_from_stage": "model_selection",
            "rerun_reason": "Model family changed.",
        }
    }

    by_stage = _blueprint_map(task)

    assert by_stage[WorkflowStage.feature_engineering].status == WorkflowStageStatus.completed
    assert by_stage[WorkflowStage.model_selection].status == WorkflowStageStatus.pending
    assert by_stage[WorkflowStage.model_selection].summary == "人工协同要求从“model_selection”所在链路重新运行。原因：Model family changed."
    assert by_stage[WorkflowStage.training_validation].status == WorkflowStageStatus.pending
    assert by_stage[WorkflowStage.report_generation].status == WorkflowStageStatus.pending
