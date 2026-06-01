from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import (
    RunAttempt,
    TaskRecord,
    TaskRunProgressResponse,
    TaskStatus,
)
from backend.app.services.codex_common import (
    CODEX_ACTIVE_STATUSES,
    CODEX_FAILED_STATUSES,
    CODEX_WAITING_STATUSES,
    CodexBackendError,
    is_quota_guard_paused,
    workspace_path_from_artifacts,
)
from backend.app.services.codex_http import CodexBackendClient
from backend.app.services.codex_metrics import build_codex_run_summary
from backend.app.services.codex_progress import (
    build_codex_run_progress_response,
    codex_activity_text,
    codex_status,
    has_completed_codex_artifacts,
)
from backend.app.services.codex_usage import token_usage_from_artifacts
from backend.app.services.codex_overview import build_codex_overview_from_artifacts
from backend.app.services.codex_workspace import CodexWorkspaceReader, read_workspace_overview_artifacts


@dataclass(frozen=True)
class _CodexSyncContext:
    workspace_path: str | None
    progress: dict[str, Any]
    metrics: dict[str, Any]
    token_usage: Any
    status: str


def start_codex_task(task: TaskRecord, settings: Settings, *, token_budget: int | None = None) -> dict[str, Any]:
    return CodexBackendClient(settings).start_task(task, token_budget=token_budget)


def approve_codex_plan(
    task: TaskRecord,
    settings: Settings,
    *,
    plan_text: str,
    token_budget: int | None = None,
) -> dict[str, Any]:
    return CodexBackendClient(settings).approve_plan(task, plan_text=plan_text, token_budget=token_budget)


def regenerate_codex_plan(task: TaskRecord, settings: Settings, *, token_budget: int | None = None) -> dict[str, Any]:
    return CodexBackendClient(settings).regenerate_plan(task, token_budget=token_budget)


def interrupt_codex_task(task: TaskRecord, settings: Settings, *, reason: str | None = None) -> dict[str, Any]:
    return CodexBackendClient(settings).interrupt_task(task, reason=reason)


def resume_codex_task(task: TaskRecord, settings: Settings, *, token_budget: int | None = None) -> dict[str, Any]:
    return CodexBackendClient(settings).resume_task(task, token_budget=token_budget)


def fetch_codex_task_status(task: TaskRecord, settings: Settings) -> dict[str, Any]:
    return CodexBackendClient(settings).task_status(task)


def fetch_latest_codex_artifacts(settings: Settings) -> dict[str, Any]:
    return CodexBackendClient(settings).fetch_latest_artifacts()


def reload_codex_config(settings: Settings) -> dict[str, Any]:
    return CodexBackendClient(settings).reload_config()


def read_codex_artifacts(task: TaskRecord, settings: Settings) -> dict[str, Any]:
    return CodexWorkspaceReader(settings).read_artifacts(task)


def build_codex_overview(task: TaskRecord, settings: Settings) -> dict[str, Any]:
    return build_codex_overview_from_artifacts(read_codex_artifacts(task, settings))


def build_codex_overview_from_workspace(workspace: Path) -> dict[str, Any]:
    return build_codex_overview_from_artifacts(read_workspace_overview_artifacts(workspace))


def resolve_codex_workspace(task: TaskRecord, settings: Settings) -> Path | None:
    return CodexWorkspaceReader(settings).resolve(task)


def build_codex_run_progress(task: TaskRecord, settings: Settings) -> TaskRunProgressResponse:
    artifacts = read_codex_artifacts(task, settings)
    return build_codex_run_progress_response(task, artifacts)


def sync_task_from_codex_artifacts(task: TaskRecord, settings: Settings) -> tuple[TaskRecord, dict[str, Any]]:
    _sync_dataset_path_from_local_storage(task, settings)
    artifacts = read_codex_artifacts(task, settings)
    context = _codex_sync_context(task, artifacts)
    now = datetime.now(timezone.utc)

    _record_codex_workspace_attempt(task, context)
    task.executor_type = "codex"
    if is_quota_guard_paused(task.status, task.structured_requirements):
        task.codex_status = "interrupted"
        _set_codex_structured_metadata(task)
        return task, artifacts

    task.codex_status = context.status
    _apply_codex_sync_status(task, artifacts, context, now)
    _set_codex_structured_metadata(task)
    return task, artifacts


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
        _apply_waiting_codex_status(task)
    elif context.status in CODEX_ACTIVE_STATUSES:
        _apply_active_codex_status(task, artifacts, context, now)
    elif context.status == "completed":
        _complete_codex_task(task, artifacts, context, now, activity_status=context.status)
    elif context.status == "interrupted":
        _apply_interrupted_codex_status(task, artifacts, context)
    elif context.status in CODEX_FAILED_STATUSES:
        _apply_failed_codex_status(task, artifacts, context, now)


def _apply_waiting_codex_status(task: TaskRecord) -> None:
    _set_human_loop_previous_status(task, previous_status=TaskStatus.running)
    task.status = TaskStatus.paused_for_review
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
    summary = build_codex_run_summary(context.workspace_path, context.metrics)
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


def codex_plan_text(task: TaskRecord, settings: Settings) -> str:
    return CodexWorkspaceReader(settings).plan_text(task)


def codex_workspace_plan_path(task: TaskRecord, settings: Settings) -> str | None:
    return CodexWorkspaceReader(settings).plan_path(task)


def _set_codex_structured_metadata(task: TaskRecord) -> None:
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    codex = structured.get("codex") if isinstance(structured.get("codex"), dict) else {}
    structured["executor_type"] = "codex"
    structured["codex"] = {
        **codex,
        "workspace_path": task.codex_workspace_path,
        "session_id": task.codex_session_id,
        "thread_id": task.codex_thread_id,
        "status": task.codex_status,
        "started_at": task.codex_started_at.isoformat() if task.codex_started_at else None,
        "finished_at": task.codex_finished_at.isoformat() if task.codex_finished_at else None,
    }
    task.structured_requirements = structured


def _set_human_loop_previous_status(task: TaskRecord, *, previous_status: TaskStatus) -> None:
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    human_loop = structured.get("human_loop") if isinstance(structured.get("human_loop"), dict) else {}
    if human_loop.get("previous_status") in {None, TaskStatus.paused_for_review.value, TaskStatus.waiting_human.value}:
        human_loop["previous_status"] = previous_status.value
    human_loop["manual_hold"] = False
    human_loop["updated_at"] = datetime.now(timezone.utc).isoformat()
    structured["human_loop"] = human_loop
    task.structured_requirements = structured


def _sync_dataset_path_from_local_storage(task: TaskRecord, settings: Settings) -> None:
    if task.dataset_path and Path(task.dataset_path).exists():
        return
    dataset_dir = settings.storage_dir / task.id / "dataset"
    if dataset_dir.is_dir():
        task.dataset_path = str(dataset_dir)
        if not task.dataset_filename:
            try:
                first_file = next(path for path in dataset_dir.iterdir() if path.is_file())
            except (OSError, StopIteration):
                first_file = None
            if first_file is not None:
                task.dataset_filename = first_file.name
        return
    candidate = settings.storage_dir / task.id / "dataset.csv"
    if not candidate.is_file():
        return
    task.dataset_path = str(candidate)
    if not task.dataset_filename:
        task.dataset_filename = candidate.name
