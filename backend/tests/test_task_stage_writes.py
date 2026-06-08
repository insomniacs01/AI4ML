from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import WorkflowStage, WorkflowStageStatus
from backend.app.services.task_stage_writes import build_stage_record_payload


def test_build_stage_record_payload_serializes_status_timing_and_preserves_existing_log() -> None:
    started_at = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)

    payload = build_stage_record_payload(
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.training_validation,
        status=WorkflowStageStatus.completed,
        selected_connector_id="connector-1",
        model_name="model-a",
        selection_source="task_override",
        summary="Training complete.",
        artifact_refs=["output/model.pkl"],
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=600.0,
        log_excerpt=None,
        existing_log_excerpt="previous logs",
    )

    assert payload == {
        "team_id": "team-1",
        "task_id": "task-1",
        "stage": "training_validation",
        "status": "completed",
        "selected_connector_id": "connector-1",
        "model_name": "model-a",
        "selection_source": "task_override",
        "summary": "Training complete.",
        "artifact_refs": ["output/model.pkl"],
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:10:00+00:00",
        "duration_seconds": 600.0,
        "log_excerpt": "previous logs",
    }


def test_build_stage_record_payload_prefers_explicit_log_excerpt() -> None:
    payload = build_stage_record_payload(
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.data_analysis,
        status=WorkflowStageStatus.running,
        selected_connector_id=None,
        model_name=None,
        selection_source=None,
        summary=None,
        artifact_refs=None,
        started_at=None,
        finished_at=None,
        duration_seconds=None,
        log_excerpt="fresh logs",
        existing_log_excerpt="previous logs",
    )

    assert payload["stage"] == "data_analysis"
    assert payload["status"] == "running"
    assert payload["log_excerpt"] == "fresh logs"
    assert payload["started_at"] is None
    assert payload["finished_at"] is None
