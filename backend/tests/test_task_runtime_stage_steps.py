from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.models.task import TaskRecord, TaskStatus, WorkflowStage, WorkflowStageStatus
from backend.app.services.task_runtime_stage_steps import workflow_steps_from_stage_records


def _task(status: TaskStatus) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-runtime-stage-steps",
        team_id="team-1",
        created_by="user-1",
        name="Runtime Stage Steps Task",
        description="Project stage records to step records.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_workflow_steps_from_stage_records_keeps_latest_ordered_by_primary_stages() -> None:
    updated_at = datetime.now(timezone.utc)
    records = [
        SimpleNamespace(
            id="data-stage",
            stage=WorkflowStage.data_analysis,
            status=WorkflowStageStatus.completed,
            summary="Data inspected",
            artifact_refs=["profile.json", "", None],
            duration_seconds=3,
            updated_at=updated_at,
        )
    ]

    steps = workflow_steps_from_stage_records(_task(TaskStatus.running), records)
    by_name = {step.name: step for step in steps}

    assert [step.name for step in steps][0] == WorkflowStage.requirement_analysis.value
    assert by_name[WorkflowStage.data_analysis.value].message == "Data inspected"
    assert by_name[WorkflowStage.data_analysis.value].artifacts == ["profile.json"]
    assert by_name[WorkflowStage.data_analysis.value].duration_s == 3
    assert by_name[WorkflowStage.data_analysis.value].updated_at == updated_at


def test_workflow_steps_from_stage_records_builds_task_status_fallbacks() -> None:
    steps = workflow_steps_from_stage_records(_task(TaskStatus.failed), [])
    by_name = {step.name: step for step in steps}

    assert by_name[WorkflowStage.requirement_analysis.value].status == WorkflowStageStatus.completed.value
    assert by_name[WorkflowStage.training_validation.value].status == WorkflowStageStatus.failed.value
