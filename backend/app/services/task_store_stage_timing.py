from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskAgentRuntimeRecord, WorkflowStageRecord, WorkflowStageStatus


def resolve_stage_timing(
    existing: WorkflowStageRecord | TaskAgentRuntimeRecord | None,
    *,
    status: WorkflowStageStatus,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime | None, float | None]:
    resolved_now = now or datetime.now(timezone.utc)
    started_at, finished_at = _stage_timing_bounds(existing, status=status, now=resolved_now)
    return started_at, finished_at, _stage_duration_seconds(started_at, finished_at)


def _stage_timing_bounds(
    existing: WorkflowStageRecord | TaskAgentRuntimeRecord | None,
    *,
    status: WorkflowStageStatus,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    if status == WorkflowStageStatus.running:
        return _running_stage_timing_bounds(existing, now)
    if status in {WorkflowStageStatus.completed, WorkflowStageStatus.failed}:
        return _terminal_stage_timing_bounds(existing, now)
    if status in {WorkflowStageStatus.pending, WorkflowStageStatus.waiting_human}:
        return _inactive_stage_timing_bounds(existing)
    return _existing_stage_timing_bounds(existing)


def _running_stage_timing_bounds(
    existing: WorkflowStageRecord | TaskAgentRuntimeRecord | None,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    started_at = existing.started_at if existing else None
    if existing is None or existing.status != WorkflowStageStatus.running:
        started_at = now
    return started_at, None


def _terminal_stage_timing_bounds(
    existing: WorkflowStageRecord | TaskAgentRuntimeRecord | None,
    now: datetime,
) -> tuple[datetime | None, datetime | None]:
    started_at = existing.started_at if existing else None
    finished_at = existing.finished_at if existing else None
    if started_at is None:
        started_at = existing.created_at if existing else now
    if finished_at is None:
        finished_at = now
    return started_at, finished_at


def _inactive_stage_timing_bounds(
    existing: WorkflowStageRecord | TaskAgentRuntimeRecord | None,
) -> tuple[datetime | None, datetime | None]:
    started_at, finished_at = _existing_stage_timing_bounds(existing)
    if started_at is None:
        finished_at = None
    return started_at, finished_at


def _existing_stage_timing_bounds(
    existing: WorkflowStageRecord | TaskAgentRuntimeRecord | None,
) -> tuple[datetime | None, datetime | None]:
    if existing is None:
        return None, None
    return existing.started_at, existing.finished_at


def _stage_duration_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return max((finished_at - started_at).total_seconds(), 0.0)
