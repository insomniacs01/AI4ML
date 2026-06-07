from __future__ import annotations

import logging
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord, TaskRuntimeSnapshotResponse
from backend.app.services.codex_backend import (
    build_codex_run_progress,
    codex_plan_text,
    read_codex_artifacts,
)
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_codex_runtime_activity import safe_reconcile_codex_runtime_activity
from backend.app.services.task_codex_runtime_snapshot_sync import (
    TaskRuntimeSnapshotSyncError,
    sync_codex_runtime_snapshot,
)
from backend.app.services.task_codex_sync import is_codex_task
from backend.app.services.task_runtime_snapshot_payload import build_task_run_payload
from backend.app.services.task_runtime_steps import build_runtime_steps, progress_from_steps


logger = logging.getLogger(__name__)


class TaskRuntimeSnapshotNotFound(LookupError):
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
                task, progress_response, codex_overview, codex_artifacts = sync_codex_runtime_snapshot(
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
