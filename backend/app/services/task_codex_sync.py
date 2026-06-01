from __future__ import annotations

import logging
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord
from backend.app.services.codex_backend import resolve_codex_workspace, sync_task_from_codex_artifacts


logger = logging.getLogger(__name__)


def is_codex_task(task: TaskRecord, settings: Settings) -> bool:
    return task.executor_type == "codex" or resolve_codex_workspace(task, settings) is not None


def sync_codex_task_state(
    task: TaskRecord,
    settings: Settings,
    *,
    task_store: Any | None = None,
    access_token: str | None = None,
    fail_on_error: bool = True,
) -> tuple[TaskRecord, dict[str, Any]]:
    try:
        previous_task = task.model_dump(mode="json")
        synced_task, artifacts = sync_task_from_codex_artifacts(task, settings)
        if task_store is not None and synced_task.model_dump(mode="json") != previous_task:
            synced_task = task_store.save_task(synced_task, access_token=access_token)
        return synced_task, artifacts
    except Exception as exc:  # noqa: BLE001
        logger.warning("Codex artifact sync failed for task %s: %s", task.id, exc)
        if fail_on_error:
            raise
        return task, {}
