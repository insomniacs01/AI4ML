from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import WorkflowStage, WorkflowStageStatus
from backend.app.services.task_agent_runtime_writes import build_agent_run_payload


def test_build_agent_run_payload_normalizes_values_and_clamps_progress() -> None:
    started_at = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)

    payload = build_agent_run_payload(
        team_id="team-1",
        task_id="task-1",
        agent_id="training_validation",
        stage=WorkflowStage.training_validation,
        name="训练验证",
        role="训练并检查结果",
        short_role="训练",
        status=WorkflowStageStatus.completed,
        progress=150,
        current_task="Training complete.",
        selected_connector_id="connector-1",
        model_name="model-a",
        selection_source="team_policy",
        artifact_refs={"model": "output/model.pkl"},
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=300.0,
        log_excerpt=None,
        existing_log_excerpt="previous logs",
        worker_id="worker-1",
    )

    assert payload == {
        "team_id": "team-1",
        "task_id": "task-1",
        "agent_id": "training_validation",
        "stage": "training_validation",
        "name": "训练验证",
        "role": "训练并检查结果",
        "short_role": "训练",
        "status": "completed",
        "progress": 100,
        "current_task": "Training complete.",
        "selected_connector_id": "connector-1",
        "model_name": "model-a",
        "selection_source": "team_policy",
        "artifact_refs": {"model": "output/model.pkl"},
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:05:00+00:00",
        "duration_seconds": 300.0,
        "log_excerpt": "previous logs",
        "worker_id": "worker-1",
    }


def test_build_agent_run_payload_prefers_explicit_log_excerpt_and_clamps_low_progress() -> None:
    payload = build_agent_run_payload(
        team_id="team-1",
        task_id="task-1",
        agent_id="data_analysis",
        stage=WorkflowStage.data_analysis,
        name="数据检查",
        role="检查数据",
        short_role="数据",
        status=WorkflowStageStatus.running,
        progress=-3,
        current_task="Inspecting data.",
        selected_connector_id=None,
        model_name=None,
        selection_source=None,
        artifact_refs=None,
        started_at=None,
        finished_at=None,
        duration_seconds=None,
        log_excerpt="fresh logs",
        existing_log_excerpt="previous logs",
        worker_id=None,
    )

    assert payload["progress"] == 0
    assert payload["log_excerpt"] == "fresh logs"
    assert payload["started_at"] is None
    assert payload["finished_at"] is None
