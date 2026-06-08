from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from backend.app.core.supabase_auth import SupabaseUser, TeamAccessContext
from backend.app.models.task import RunSummary, TaskRecord, TaskStatus, WorkflowStage, WorkflowStageStatus
from backend.app.services.task_runtime_progress import record_codex_status_stages


def _task(status: TaskStatus) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-runtime-progress",
        team_id="team-1",
        created_by="user-1",
        name="Runtime Progress Task",
        description="Record Codex stage progress.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _team_access() -> TeamAccessContext:
    return TeamAccessContext(
        team_id="team-1",
        role="admin",
        user=SupabaseUser(id="user-1", email=None, raw={}),
        access_token="token",
    )


def test_record_codex_status_stages_records_plan_gate_payload() -> None:
    task = _task(TaskStatus.paused_for_review)
    task.codex_workspace_path = "workspace"

    with patch(
        "backend.app.services.task_runtime_progress.codex_workspace_plan_path",
        return_value="workspace/output/plan.md",
    ), patch(
        "backend.app.services.task_runtime_progress.ensure_codex_plan_request"
    ) as ensure_request, patch(
        "backend.app.services.task_runtime_progress._record_stage_selection_map"
    ) as record_map:
        record_codex_status_stages(task, _team_access(), artifacts={})

    ensure_request.assert_called_once_with(task, _team_access(), plan_path="workspace/output/plan.md")
    _, _, kwargs = record_map.mock_calls[0]
    assert kwargs["status_by_stage"][WorkflowStage.data_analysis] == WorkflowStageStatus.waiting_human
    assert kwargs["status_by_stage"][WorkflowStage.feature_engineering] == WorkflowStageStatus.pending
    assert kwargs["summary_by_stage"][WorkflowStage.data_analysis] == "Codex 已生成计划，等待人工确认。"
    assert kwargs["artifact_refs"] == ["workspace", "workspace/output/plan.md"]


def test_record_codex_status_stages_records_completed_run_payload() -> None:
    task = _task(TaskStatus.completed)
    task.codex_workspace_path = "workspace"
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir="workspace",
    )

    with patch(
        "backend.app.services.task_runtime_progress.codex_workspace_plan_path",
        return_value="workspace/output/plan.md",
    ), patch(
        "backend.app.services.task_runtime_progress.collect_stage_artifacts_by_stage",
        return_value={WorkflowStage.training_validation: ["workspace/output/metrics.json"]},
    ), patch(
        "backend.app.services.task_runtime_progress.read_run_log_excerpt",
        return_value="run log",
    ), patch(
        "backend.app.services.task_runtime_progress._record_stage_selection_map"
    ) as record_map:
        record_codex_status_stages(task, _team_access(), artifacts={})

    _, _, kwargs = record_map.mock_calls[0]
    assert kwargs["status_by_stage"][WorkflowStage.report_generation] == WorkflowStageStatus.completed
    assert kwargs["summary_by_stage"][WorkflowStage.model_selection] == "Codex 已选择最终模型：ridge。"
    assert kwargs["summary_by_stage"][WorkflowStage.training_validation] == "Codex 验证完成：mae = 2。"
    assert kwargs["artifact_refs"] == ["workspace"]
    assert kwargs["artifact_refs_by_stage"] == {WorkflowStage.training_validation: ["workspace/output/metrics.json"]}
    assert kwargs["log_excerpt_by_stage"][WorkflowStage.report_generation] == "run log"
