from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.task_cache_payloads import (
    decode_human_request_payload,
    decode_stage_payload,
    decode_task_payload,
    encode_human_request_payload,
    encode_stage_payload,
    encode_task_payload,
)


def test_task_cache_payload_round_trips_task_records() -> None:
    now = datetime.now(timezone.utc)
    task = TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Payload Task",
        description="Cached payload.",
        status=TaskStatus.running,
        created_at=now,
        updated_at=now,
    )

    decoded = decode_task_payload(encode_task_payload(task))

    assert decoded is not None
    assert decoded.id == task.id
    assert decoded.status == TaskStatus.running


def test_task_cache_payload_round_trips_stage_records() -> None:
    now = datetime.now(timezone.utc)
    record = WorkflowStageRecord(
        id="stage-1",
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.training_validation,
        status=WorkflowStageStatus.running,
        created_at=now,
        updated_at=now,
    )

    decoded = decode_stage_payload(encode_stage_payload(record))

    assert decoded is not None
    assert decoded.stage == WorkflowStage.training_validation
    assert decoded.status == WorkflowStageStatus.running


def test_task_cache_payload_round_trips_human_request_records() -> None:
    now = datetime.now(timezone.utc)
    record = TaskHumanRequestRecord(
        id="request-1",
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.training_validation,
        status=HumanInteractionRequestStatus.pending,
        payload={"title": "Review"},
        created_at=now,
        updated_at=now,
    )

    decoded = decode_human_request_payload(encode_human_request_payload(record))

    assert decoded is not None
    assert decoded.id == "request-1"
    assert decoded.status == HumanInteractionRequestStatus.pending
    assert decoded.payload == {"title": "Review"}


def test_task_cache_payload_decoders_ignore_invalid_payloads() -> None:
    assert decode_task_payload("{not-json") is None
    assert decode_stage_payload("{not-json") is None
    assert decode_human_request_payload("{not-json") is None
