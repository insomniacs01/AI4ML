from __future__ import annotations

import logging
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord, TaskRuntimeSnapshotResponse
from backend.app.services.codex_backend import (
    build_codex_overview,
    build_codex_run_progress,
    codex_plan_text,
    read_codex_artifacts,
)
from backend.app.services.quota_runtime_guard import pause_codex_task_for_quota
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_codex_human_requests import ensure_codex_improvement_request, ensure_codex_plan_request
from backend.app.services.task_codex_improvement_review import has_codex_improvement_review
from backend.app.services.task_codex_runtime_activity import safe_reconcile_codex_runtime_activity
from backend.app.services.task_codex_sync import is_codex_task, sync_codex_task_state
from backend.app.services.task_codex_token_ledger import sync_codex_token_ledger
from backend.app.services.task_runtime_snapshot_payload import build_task_run_payload
from backend.app.services.task_runtime_steps import build_runtime_steps, progress_from_steps


logger = logging.getLogger(__name__)


class TaskRuntimeSnapshotNotFound(LookupError):
    pass


class TaskRuntimeSnapshotSyncError(RuntimeError):
    pass


def build_task_runtime_snapshot_response(
    task_id: str,
    team_access: TeamAccessContext,
    *,
    sync_runtime: bool = True,
) -> TaskRuntimeSnapshotResponse:
    task_store = get_task_store()
    task = task_store.get_task(
        team_access.team_id,
        task_id,
        access_token=team_access.access_token,
        allow_stale_cache=True,
    )
    if task is None:
        raise TaskRuntimeSnapshotNotFound("task not found")

    settings = get_settings()
    should_sync_codex = is_codex_task(task, settings)
    if should_sync_codex:
        progress_response = None
        codex_overview = {}
        codex_artifacts = {}
        if sync_runtime:
            try:
                task, progress_response, codex_overview, codex_artifacts = _sync_codex_runtime_snapshot(
                    task_store,
                    task,
                    team_access,
                    settings,
                )
            except TaskRuntimeSnapshotSyncError as exc:
                logger.warning(
                    "Codex runtime snapshot sync failed for task %s; returning cached runtime state: %s",
                    task.id,
                    exc,
                )
        task = safe_reconcile_codex_runtime_activity(task_store, task, team_access, settings)
        progress_response = _safe_build_codex_run_progress(task, settings) or progress_response
        if not codex_artifacts:
            codex_artifacts = _safe_read_codex_artifacts(task, settings)
    else:
        progress_response = None
        codex_overview = {}
        codex_artifacts = {}

    stage_records = [] if should_sync_codex else _list_stage_records_for_snapshot(task_store, task_id, team_access)

    steps = build_runtime_steps(task, stage_records, progress=progress_response)
    progress = progress_from_steps(task, steps)
    plan_text = _safe_codex_plan_text(task, settings) if should_sync_codex else ""
    return TaskRuntimeSnapshotResponse(
        task=task,
        task_run=build_task_run_payload(
            task,
            steps,
            progress_response,
            progress,
            codex_overview,
            should_sync_codex=should_sync_codex,
            codex_plan=plan_text,
            codex_artifacts=codex_artifacts,
        ),
    )


def _build_fast_codex_runtime_snapshot(task: TaskRecord, settings: Any) -> tuple[Any | None, dict[str, Any]]:
    try:
        return build_codex_run_progress(task, settings), {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Fast Codex runtime snapshot fell back to cached task state for task %s: %s", task.id, exc)
        return None, {}


def _safe_build_codex_run_progress(task: TaskRecord, settings: Any) -> Any | None:
    try:
        return build_codex_run_progress(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not build Codex runtime progress for task %s: %s", task.id, exc)
        return None


def _safe_codex_plan_text(task: TaskRecord, settings: Any) -> str:
    try:
        return codex_plan_text(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Codex plan text for task %s: %s", task.id, exc)
        return ""


def _safe_read_codex_artifacts(task: TaskRecord, settings: Any) -> dict[str, Any]:
    try:
        artifacts = read_codex_artifacts(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Codex artifacts for task %s: %s", task.id, exc)
        return {}
    return artifacts if isinstance(artifacts, dict) else {}


def _sync_codex_runtime_snapshot(
    task_store: Any,
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Any,
) -> tuple[TaskRecord, Any, dict[str, Any], dict[str, Any]]:
    try:
        task.executor_type = "codex"
        task, artifacts = sync_codex_task_state(
            task,
            settings,
            task_store=task_store,
            access_token=team_access.access_token,
        )
        progress_response = build_codex_run_progress(task, settings)
        codex_overview = build_codex_overview(task, settings)
        quota_exhausted = sync_codex_token_ledger(task_store, task, team_access)
        if quota_exhausted:
            task = pause_codex_task_for_quota(task_store, task, team_access)
            progress_response = build_codex_run_progress(task, settings)
        if progress_response.status == "blocked" and task.codex_status != "interrupted":
            try:
                if has_codex_improvement_review(artifacts):
                    ensure_codex_improvement_request(task, team_access, artifacts=artifacts)
                else:
                    ensure_codex_plan_request(task, team_access)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not sync Codex review request for task %s: %s", task.id, exc)
        return task, progress_response, codex_overview, artifacts
    except Exception as exc:  # noqa: BLE001
        raise TaskRuntimeSnapshotSyncError(f"Codex runtime snapshot sync failed: {exc}") from exc


def _list_stage_records_for_snapshot(task_store: Any, task_id: str, team_access: TeamAccessContext) -> list[Any]:
    try:
        return task_store.list_stage_records(
            team_access.team_id,
            task_id,
            access_token=team_access.access_token,
            allow_stale_cache=True,
        )
    except (RuntimeError, PermissionError, ConnectionError):
        return []
