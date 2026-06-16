from __future__ import annotations

import logging
from typing import Any

from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord
from backend.app.services.codex_backend import build_codex_overview, build_codex_run_progress
from backend.app.services.quota_runtime_guard import pause_codex_task_for_quota
from backend.app.services.task_codex_human_requests import ensure_codex_improvement_request, ensure_codex_plan_request
from backend.app.services.task_codex_improvement_review import has_codex_improvement_review
from backend.app.services.task_codex_sync import sync_codex_task_state
from backend.app.services.task_codex_token_ledger import sync_codex_token_ledger
from backend.app.services.task_runtime_resume import codex_waiting_plan_approval


logger = logging.getLogger(__name__)


class TaskRuntimeSnapshotSyncError(RuntimeError):
    pass


def sync_codex_runtime_snapshot(
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
            ensure_codex_review_request(task, team_access, artifacts, suppress_errors=True)
        return task, progress_response, codex_overview, artifacts
    except Exception as exc:  # noqa: BLE001
        raise TaskRuntimeSnapshotSyncError(f"Codex runtime snapshot sync failed: {exc}") from exc


def ensure_codex_review_request(
    task: TaskRecord,
    team_access: TeamAccessContext,
    artifacts: dict[str, Any],
    *,
    suppress_errors: bool = False,
) -> None:
    try:
        progress = artifacts.get("progress") if isinstance(artifacts.get("progress"), dict) else {}
        if has_codex_improvement_review(artifacts):
            ensure_codex_improvement_request(task, team_access, artifacts=artifacts)
        elif codex_waiting_plan_approval(task, progress):
            ensure_codex_plan_request(task, team_access)
    except Exception as exc:  # noqa: BLE001
        if not suppress_errors:
            raise
        logger.warning("Could not sync Codex review request for task %s: %s", task.id, exc)
