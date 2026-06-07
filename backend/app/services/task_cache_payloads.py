from __future__ import annotations

import json

from backend.app.models.task import TaskRecord, WorkflowStageRecord


def encode_task_payload(task: TaskRecord) -> str:
    return json.dumps(task.model_dump(mode="json"), ensure_ascii=False)


def decode_task_payload(payload: str) -> TaskRecord | None:
    try:
        return TaskRecord.model_validate(json.loads(payload))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def encode_stage_payload(record: WorkflowStageRecord) -> str:
    return json.dumps(record.model_dump(mode="json"), ensure_ascii=False)


def decode_stage_payload(payload: str) -> WorkflowStageRecord | None:
    try:
        return WorkflowStageRecord.model_validate(json.loads(payload))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
