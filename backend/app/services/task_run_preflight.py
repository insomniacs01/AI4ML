from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord, TaskRunRequest
from backend.app.services.platform_limits import (
    assert_time_budget_within_limit,
    assert_user_can_start_task,
)
from backend.app.services.task_human_parameter_guidance import resolve_task_run_time_limit
from backend.app.services.task_store import TaskStore


def task_requested_time_limit(task: TaskRecord, payload: TaskRunRequest) -> int | None:
    if payload.time_limit is not None:
        return payload.time_limit
    return resolve_task_run_time_limit(task, None)


def assert_task_run_preflight(
    task_store: TaskStore,
    task: TaskRecord,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
    *,
    settings: Settings,
) -> None:
    all_tasks = task_store.list_tasks(
        team_access.team_id,
        access_token=team_access.access_token,
        lightweight=True,
        prefer_cache=False,
    )
    assert_user_can_start_task(
        settings,
        tasks=all_tasks,
        user_id=team_access.user.id,
        task_id=task.id,
    )
    assert_time_budget_within_limit(settings, task_requested_time_limit(task, payload))
