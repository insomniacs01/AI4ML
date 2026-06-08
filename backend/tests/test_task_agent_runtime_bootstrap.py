from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.supabase_auth import SupabaseUser, TeamAccessContext
from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.task_agent_runtime_bootstrap import build_missing_agent_runtimes
from backend.app.services.task_workflow_tracking import _ensure_agent_runtime_records


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task() -> TaskRecord:
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Runtime bootstrap",
        description="Backfill missing agent runtime records.",
        status=TaskStatus.running,
        created_at=NOW,
        updated_at=NOW,
    )


def _team_access() -> TeamAccessContext:
    return TeamAccessContext(
        team_id="team-1",
        role="admin",
        user=SupabaseUser(id="user-1", email=None, raw={}),
        access_token="access-token",
    )


def _stage(
    stage: WorkflowStage,
    *,
    status: WorkflowStageStatus = WorkflowStageStatus.running,
    summary: str | None = None,
) -> WorkflowStageRecord:
    return WorkflowStageRecord(
        id=f"stage-{stage.value}",
        team_id="team-1",
        task_id="task-1",
        stage=stage,
        status=status,
        summary=summary,
        selected_connector_id="connector-1",
        model_name="model-a",
        selection_source="team_policy",
        artifact_refs=["output/result.json"],
        log_excerpt="stage log",
        created_at=NOW,
        updated_at=NOW,
    )


def _human_request(
    stage: WorkflowStage,
    *,
    status: HumanInteractionRequestStatus = HumanInteractionRequestStatus.open,
) -> TaskHumanRequestRecord:
    return TaskHumanRequestRecord(
        id=f"request-{stage.value}",
        team_id="team-1",
        task_id="task-1",
        stage=stage,
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _agent_run(stage: WorkflowStage) -> TaskAgentRuntimeRecord:
    return TaskAgentRuntimeRecord(
        id=f"run-{stage.value}",
        team_id="team-1",
        task_id="task-1",
        agent_id=stage.value,
        stage=stage,
        name="Existing agent",
        role="Existing role",
        short_role="Existing",
        status=WorkflowStageStatus.completed,
        current_task="Already recorded.",
        created_at=NOW,
        updated_at=NOW,
    )


class RuntimeStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def upsert_agent_run(self, **kwargs: Any) -> TaskAgentRuntimeRecord:
        self.calls.append(kwargs)
        return TaskAgentRuntimeRecord(
            id=f"created-{kwargs['agent_id']}",
            team_id=kwargs["team_id"],
            task_id=kwargs["task_id"],
            agent_id=kwargs["agent_id"],
            stage=kwargs["stage"],
            name=kwargs["name"],
            role=kwargs["role"],
            short_role=kwargs["short_role"],
            status=kwargs["status"],
            progress=kwargs["progress"],
            current_task=kwargs["current_task"],
            selected_connector_id=kwargs["selected_connector_id"],
            model_name=kwargs["model_name"],
            selection_source=kwargs["selection_source"],
            artifact_refs=kwargs["artifact_refs"],
            log_excerpt=kwargs["log_excerpt"],
            worker_id=kwargs["worker_id"],
            created_at=NOW,
            updated_at=NOW,
        )


def test_missing_agent_runtimes_use_stage_records_and_waiting_human_override() -> None:
    existing_run = _agent_run(WorkflowStage.requirement_analysis)

    runtimes = build_missing_agent_runtimes(
        task_id="task-1",
        stages=[
            _stage(
                WorkflowStage.training_validation,
                status=WorkflowStageStatus.completed,
                summary="Validation result is ready.",
            )
        ],
        human_requests=[_human_request(WorkflowStage.training_validation)],
        agent_runs=[existing_run],
    )

    assert WorkflowStage.requirement_analysis.value not in {runtime.agent_id for runtime in runtimes}
    training_runtime = next(runtime for runtime in runtimes if runtime.agent_id == "training_validation")
    assert training_runtime.status == WorkflowStageStatus.waiting_human
    assert training_runtime.progress == 48
    assert training_runtime.current_task == "Validation result is ready."
    assert training_runtime.selected_connector_id == "connector-1"
    assert training_runtime.model_name == "model-a"
    assert training_runtime.selection_source == "team_policy"
    assert training_runtime.artifact_refs == ["output/result.json"]
    assert training_runtime.log_excerpt == "stage log"
    assert training_runtime.worker_id == "backend-agent-worker:task-1:training_validation"


def test_ensure_agent_runtime_records_upserts_only_missing_runtimes(monkeypatch) -> None:
    store = RuntimeStore()
    monkeypatch.setattr("backend.app.services.task_workflow_tracking.get_task_store", lambda: store)
    existing_run = _agent_run(WorkflowStage.requirement_analysis)

    records = _ensure_agent_runtime_records(
        _task(),
        _team_access(),
        stages=[_stage(WorkflowStage.data_analysis, summary="Inspect dataset.")],
        human_requests=[_human_request(WorkflowStage.data_analysis)],
        agent_runs=[existing_run],
    )

    assert records[0] is existing_run
    assert len(store.calls) == 5
    assert {call["agent_id"] for call in store.calls}.isdisjoint({"requirement_analysis"})
    data_call = next(call for call in store.calls if call["agent_id"] == "data_analysis")
    assert data_call["access_token"] == "access-token"
    assert data_call["status"] == WorkflowStageStatus.waiting_human
    assert data_call["progress"] == 48
    assert data_call["current_task"] == "Inspect dataset."
    assert data_call["model_name"] == "model-a"
    assert records[-1].agent_id == "report_generation"
