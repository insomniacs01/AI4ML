from __future__ import annotations

import logging
from typing import Any

from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_backend import fetch_codex_task_status
from backend.app.services.codex_common import CODEX_ACTIVE_STATUSES
from backend.app.services.task_codex_sync import sync_codex_task_state


logger = logging.getLogger(__name__)


def safe_reconcile_codex_runtime_activity(
    task_store: Any,
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Any,
) -> TaskRecord:
    try:
        return reconcile_codex_runtime_activity(task_store, task, team_access, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reconcile Codex runtime activity for task %s: %s", task.id, exc)
        return task


def reconcile_codex_runtime_activity(
    task_store: Any,
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Any,
) -> TaskRecord:
    if not codex_runtime_probe_needed(task):
        return task
    try:
        status_payload = fetch_codex_task_status(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not verify Codex runtime activity for task %s: %s", task.id, exc)
        return task

    if status_payload.get("running") is True:
        return task

    synced_task, _artifacts = sync_codex_task_state(
        task,
        settings,
        task_store=task_store,
        access_token=team_access.access_token,
        fail_on_error=False,
    )
    if not codex_runtime_probe_needed(synced_task):
        return synced_task

    synced_task.status = TaskStatus.paused_for_review
    synced_task.codex_status = "interrupted"
    synced_task.codex_finished_at = None
    synced_task.notes = "Codex 当前没有运行中的执行轮次，已停止显示为运行中；可从现有工作区继续。"
    try:
        return task_store.save_task(synced_task, access_token=team_access.access_token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist inactive Codex runtime state for task %s: %s", task.id, exc)
        return synced_task


def codex_runtime_probe_needed(task: TaskRecord) -> bool:
    if not (task.codex_session_id or task.codex_workspace_path):
        return False
    codex_status_value = str(task.codex_status or "").strip()
    return task.status == TaskStatus.running or codex_status_value in CODEX_ACTIVE_STATUSES
