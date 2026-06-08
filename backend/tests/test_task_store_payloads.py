from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import WorkflowStage
from backend.app.services.task_store_payloads import TaskPayloadMapper


def test_stage_payload_normalizes_legacy_stage() -> None:
    now = datetime.now(timezone.utc)

    record = TaskPayloadMapper._stage_record_from_payload(
        {
            "id": "stage-1",
            "team_id": "team-1",
            "task_id": "task-1",
            "stage": "code_generation",
            "status": "completed",
            "created_at": now,
            "updated_at": now,
        }
    )

    assert record.stage == WorkflowStage.feature_engineering


def test_agent_event_payload_backfills_time_and_flattens_artifacts() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    record = TaskPayloadMapper._agent_event_from_payload(
        {
            "id": "event-1",
            "team_id": "team-1",
            "task_id": "task-1",
            "agent_id": "agent-1",
            "stage": "execution_validation",
            "kind": "agent",
            "status": "completed",
            "text": "validated",
            "artifact_refs": {"profile": ["output/profile.json"], "report": "output/report.md"},
            "created_at": now,
        }
    )

    assert record.stage == WorkflowStage.training_validation
    assert record.time == now
    assert record.artifact_refs == ["output/profile.json", "report: output/report.md"]


def test_agent_message_payload_sanitizes_payload_and_preserves_explicit_time() -> None:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    explicit_time = datetime(2026, 1, 2, tzinfo=timezone.utc)

    record = TaskPayloadMapper._agent_message_from_payload(
        {
            "id": "message-1",
            "team_id": "team-1",
            "task_id": "task-1",
            "from_agent_id": "agent-1",
            "stage": "report_review",
            "message_type": "result",
            "status": "sent",
            "content": "report ready",
            "payload": "invalid",
            "artifact_refs": ["output/report.md", ""],
            "created_at": created_at,
            "time": explicit_time,
        }
    )

    assert record.stage == WorkflowStage.report_generation
    assert record.time == explicit_time
    assert record.payload is None
    assert record.artifact_refs == ["output/report.md"]
