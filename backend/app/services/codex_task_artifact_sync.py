from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import RunAttempt, TaskRecord, TaskStatus, TokenUsageReport
from backend.app.services.codex_artifact_state import has_completed_codex_artifacts
from backend.app.services.codex_common import (
    CODEX_ACTIVE_STATUSES,
    CODEX_FAILED_STATUSES,
    CODEX_WAITING_STATUSES,
    is_quota_guard_paused,
    workspace_path_from_artifacts,
)
from backend.app.services.codex_metrics import build_codex_run_summary
from backend.app.services.codex_progress_state import codex_activity_text, codex_status
from backend.app.services.codex_usage import token_usage_from_artifacts
from backend.app.services.task_codex_metadata import update_codex_structured_metadata
from backend.app.services.task_human_context import ensure_task_human_loop


@dataclass(frozen=True)
class _CodexSyncContext:
    workspace_path: str | None
    progress: dict[str, Any]
    metrics: dict[str, Any]
    token_usage: TokenUsageReport | None
    status: str


def apply_codex_artifact_sync(
    task: TaskRecord,
    artifacts: dict[str, Any],
    *,
    now: datetime | None = None,
) -> TaskRecord:
    context = _codex_sync_context(task, artifacts)
    sync_time = now or datetime.now(timezone.utc)

    _record_codex_workspace_attempt(task, context)
    task.executor_type = "codex"
    if is_quota_guard_paused(task.status, task.structured_requirements):
        task.codex_status = "interrupted"
        update_codex_structured_metadata(task)
        return task

    task.codex_status = context.status
    _apply_codex_sync_status(task, artifacts, context, sync_time)
    update_codex_structured_metadata(task)
    return task


def _codex_sync_context(task: TaskRecord, artifacts: dict[str, Any]) -> _CodexSyncContext:
    progress = artifacts.get("progress") if isinstance(artifacts.get("progress"), dict) else {}
    metrics = artifacts.get("metrics") if isinstance(artifacts.get("metrics"), dict) else {}
    return _CodexSyncContext(
        workspace_path=workspace_path_from_artifacts(artifacts),
        progress=progress,
        metrics=metrics,
        token_usage=token_usage_from_artifacts(artifacts),
        status=codex_status(task, progress),
    )


def _record_codex_workspace_attempt(task: TaskRecord, context: _CodexSyncContext) -> None:
    if not context.workspace_path:
        return
    task.codex_workspace_path = context.workspace_path
    task.last_run_attempt = RunAttempt(output_dir=context.workspace_path, token_usage=context.token_usage)


def _apply_codex_sync_status(
    task: TaskRecord,
    artifacts: dict[str, Any],
    context: _CodexSyncContext,
    now: datetime,
) -> None:
    if context.status in CODEX_WAITING_STATUSES:
        _apply_waiting_codex_status(task, context.status)
    elif context.status in CODEX_ACTIVE_STATUSES:
        _apply_active_codex_status(task, artifacts, context, now)
    elif context.status == "completed":
        _complete_codex_task(task, artifacts, context, now, activity_status=context.status)
    elif context.status == "interrupted":
        _apply_interrupted_codex_status(task, artifacts, context)
    elif context.status in CODEX_FAILED_STATUSES:
        _apply_failed_codex_status(task, artifacts, context, now)


def _apply_waiting_codex_status(task: TaskRecord, status_value: str) -> None:
    _set_human_loop_previous_status(task, previous_status=TaskStatus.running)
    task.status = TaskStatus.paused_for_review
    if status_value == "waiting_improvement_review":
        task.notes = "Codex 已生成改进决策方案，等待用户选择继续改进或停止并生成报告。"
    else:
        task.notes = "Codex 已生成建模计划，等待人工确认后继续执行。"


def _apply_active_codex_status(
    task: TaskRecord,
    artifacts: dict[str, Any],
    context: _CodexSyncContext,
    now: datetime,
) -> None:
    if has_completed_codex_artifacts(artifacts):
        _complete_codex_task(task, artifacts, context, now, activity_status="completed")
        return
    task.status = TaskStatus.running
    task.notes = codex_activity_text(task, context.progress, context.status, artifacts)


def _complete_codex_task(
    task: TaskRecord,
    artifacts: dict[str, Any],
    context: _CodexSyncContext,
    now: datetime,
    *,
    activity_status: str,
) -> None:
    overview = artifacts.get("overview") if isinstance(artifacts.get("overview"), dict) else None
    summary = build_codex_run_summary(context.workspace_path, context.metrics, overview=overview)
    if summary is not None:
        task.last_run = summary
        task.last_run_attempt = RunAttempt(output_dir=summary.output_dir, token_usage=summary.token_usage)
    task.status = TaskStatus.completed
    task.codex_status = "completed"
    task.codex_finished_at = task.codex_finished_at or now
    task.notes = codex_activity_text(task, context.progress, activity_status, artifacts)


def _apply_interrupted_codex_status(
    task: TaskRecord,
    artifacts: dict[str, Any],
    context: _CodexSyncContext,
) -> None:
    if task.status in {TaskStatus.cancelled, TaskStatus.completed, TaskStatus.failed, TaskStatus.published}:
        return
    task.status = TaskStatus.paused_for_review
    task.codex_status = "interrupted"
    task.notes = codex_activity_text(task, context.progress, context.status, artifacts)


def _apply_failed_codex_status(
    task: TaskRecord,
    artifacts: dict[str, Any],
    context: _CodexSyncContext,
    now: datetime,
) -> None:
    activity = codex_activity_text(task, context.progress, context.status, artifacts)
    task.status = TaskStatus.failed
    task.codex_finished_at = task.codex_finished_at or now
    if context.workspace_path:
        task.last_run_attempt = RunAttempt(
            output_dir=context.workspace_path,
            diagnosis="Codex task did not complete successfully.",
            diagnosis_detail=activity,
        )
    task.notes = activity


def _set_human_loop_previous_status(task: TaskRecord, *, previous_status: TaskStatus) -> None:
    human_loop = ensure_task_human_loop(task)
    if human_loop.get("previous_status") in {None, TaskStatus.paused_for_review.value, TaskStatus.waiting_human.value}:
        human_loop["previous_status"] = previous_status.value
    human_loop["manual_hold"] = False
    human_loop["updated_at"] = datetime.now(timezone.utc).isoformat()
