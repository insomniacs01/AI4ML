from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.models.task import TaskRecord


TASK_SUMMARY_FIELDS = (
    "created_by",
    "creator_user_id",
    "name",
    "description",
    "workflow_id",
    "label_column",
    "problem_type",
    "status",
    "dataset_filename",
    "dataset_path",
    "notes",
    "routing_policy_id",
    "routing_source",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class CachedTaskState:
    task: TaskRecord | None
    updated_at: datetime | None
    is_detail: bool


@dataclass(frozen=True)
class TaskUpsertPlan:
    task: TaskRecord
    is_detail: bool
    should_write: bool


def build_task_upsert_plan(existing: CachedTaskState | None, task: TaskRecord, *, detail: bool) -> TaskUpsertPlan:
    if existing is None:
        return TaskUpsertPlan(task=task, is_detail=detail, should_write=True)

    incoming_updated_at = task.updated_at
    if existing.is_detail and not detail:
        if existing_is_newer_or_equal(existing.updated_at, incoming_updated_at):
            return TaskUpsertPlan(task=task, is_detail=detail, should_write=False)
        if existing.task is not None:
            task = merge_summary_into_detail(existing.task, task)

    incoming_is_detail = detail or existing.is_detail
    if existing_is_newer_or_equal(existing.updated_at, incoming_updated_at) and existing.is_detail == incoming_is_detail:
        return TaskUpsertPlan(task=task, is_detail=incoming_is_detail, should_write=False)
    return TaskUpsertPlan(task=task, is_detail=incoming_is_detail, should_write=True)


def existing_is_newer_or_equal(
    existing_updated_at: datetime | None,
    incoming_updated_at: datetime | None,
) -> bool:
    return (
        existing_updated_at is not None
        and incoming_updated_at is not None
        and existing_updated_at >= incoming_updated_at
    )


def merge_summary_into_detail(detail_task: TaskRecord, summary_task: TaskRecord) -> TaskRecord:
    payload = detail_task.model_dump(mode="json")
    summary_payload = summary_task.model_dump(mode="json")
    for key in TASK_SUMMARY_FIELDS:
        payload[key] = summary_payload.get(key)
    return TaskRecord.model_validate(payload)
