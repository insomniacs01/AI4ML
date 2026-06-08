from __future__ import annotations

from typing import Any, TypeVar

from backend.app.models.task import WorkflowStage, normalize_workflow_stage


StageRecordT = TypeVar("StageRecordT")


def normalize_payload_stage(value: object) -> WorkflowStage:
    if isinstance(value, WorkflowStage):
        return normalize_workflow_stage(value)
    return normalize_workflow_stage(str(value))


def normalize_record_stage(record: StageRecordT) -> StageRecordT:
    setattr(record, "stage", normalize_payload_stage(getattr(record, "stage")))
    return record


def payload_with_created_time(payload: dict[str, Any]) -> dict[str, Any]:
    record_payload = dict(payload)
    if "time" not in record_payload:
        record_payload["time"] = record_payload.get("created_at")
    return record_payload
