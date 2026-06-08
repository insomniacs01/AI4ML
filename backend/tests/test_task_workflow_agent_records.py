from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    TaskRecord,
    TaskStageRoutingRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.task_workflow_agent_records import build_workflow_stage_tracking_context


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Workflow Agent",
        description="Track agent runtime records.",
        status=TaskStatus.uploaded,
        created_at=now,
        updated_at=now,
    )


def test_build_workflow_stage_tracking_context_uses_selection_and_agent_definition() -> None:
    stage_record = TaskStageRoutingRecord(
        stage=WorkflowStage.data_analysis,
        connector_id="connector-1",
        model_name="model-a",
        selection_source="team_policy",
    )

    context = build_workflow_stage_tracking_context(
        _task(),
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.running,
        summary="Inspect dataset columns.",
        stage_record=stage_record,
    )

    assert context.agent_id == "data_analysis"
    assert context.agent_name == "数据检查"
    assert context.agent_role == "检查数据"
    assert context.agent_short_role == "数据"
    assert context.progress == 62
    assert context.selected_connector_id == "connector-1"
    assert context.model_name == "model-a"
    assert context.selection_source == "team_policy"
    assert context.worker_id == "backend-agent-worker:task-1:data_analysis"
    assert context.event_text == "数据检查（检查数据）执行中：Inspect dataset columns."


def test_build_workflow_stage_tracking_context_defaults_missing_selection_fields() -> None:
    context = build_workflow_stage_tracking_context(
        _task(),
        stage=WorkflowStage.report_generation,
        stage_status=WorkflowStageStatus.completed,
        summary="Write final report.",
        stage_record=None,
    )

    assert context.agent_id == "report_generation"
    assert context.progress == 100
    assert context.selected_connector_id is None
    assert context.model_name is None
    assert context.selection_source is None
    assert context.status_value == "completed"
