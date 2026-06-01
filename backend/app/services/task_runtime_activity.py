from __future__ import annotations

from datetime import datetime

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_codex_sync import sync_codex_task_state

ACTIVE_CODEX_TASK_STATUSES = {
    TaskStatus.running.value,
}
NON_BLOCKING_CODEX_TASK_STATUSES = {
    TaskStatus.paused_for_review.value,
    TaskStatus.waiting_human.value,
}
TERMINAL_TASK_STATUSES = {
    TaskStatus.completed.value,
    TaskStatus.failed.value,
    TaskStatus.cancelled.value,
    TaskStatus.published.value,
}
ACTIVE_CODEX_BACKEND_STATUSES = {
    "running",
    "in_progress",
    "executing",
    "initializing",
    "starting",
    "modeling",
}
CODEX_ACTIVITY_STATUS_PRIORITY = {
    TaskStatus.running.value: 0,
}


class ActiveCodexTaskConflict(RuntimeError):
    def __init__(self, current_task: TaskRecord) -> None:
        self.current_task = current_task
        super().__init__(
            f"已有 Codex 任务正在进行：{current_task.name} ({current_task.id})。"
            "当前执行端一次只能运行一个任务；请先在工作台处理、完成或取消该任务。"
            "历史任务保持只读，不能启动或控制运行。"
        )


def status_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def is_codex_task(task: TaskRecord) -> bool:
    return task.executor_type == "codex"


def is_active_codex_task(task: TaskRecord) -> bool:
    if not is_codex_task(task):
        return False
    task_status = status_value(task.status)
    if task_status in TERMINAL_TASK_STATUSES:
        return False
    if task_status in NON_BLOCKING_CODEX_TASK_STATUSES:
        return False
    if task_status in ACTIVE_CODEX_TASK_STATUSES:
        return True
    codex_status = status_value(task.codex_status).lower()
    return bool(task.codex_workspace_path and codex_status in ACTIVE_CODEX_BACKEND_STATUSES)


def sync_codex_activity_candidate(task: TaskRecord, team_access: TeamAccessContext) -> TaskRecord:
    if status_value(task.status) in NON_BLOCKING_CODEX_TASK_STATUSES:
        return task
    if not task.codex_workspace_path:
        return task
    synced_task, _artifacts = sync_codex_task_state(
        task,
        get_settings(),
        task_store=get_task_store(),
        access_token=team_access.access_token,
        fail_on_error=False,
    )
    return synced_task


def list_active_codex_tasks(team_access: TeamAccessContext) -> list[TaskRecord]:
    task_store = get_task_store()
    tasks = task_store.list_tasks(
        team_access.team_id,
        access_token=team_access.access_token,
        lightweight=False,
        limit=200,
        prefer_cache=False,
    )
    active_tasks: list[TaskRecord] = []
    for candidate in tasks:
        if not is_codex_task(candidate):
            continue
        synced_candidate = sync_codex_activity_candidate(candidate, team_access)
        if is_active_codex_task(synced_candidate):
            active_tasks.append(synced_candidate)
    return sorted(active_tasks, key=codex_activity_sort_key)


def ensure_task_controls_current_codex_activity(
    task: TaskRecord,
    team_access: TeamAccessContext,
) -> TaskRecord:
    active_tasks = list_active_codex_tasks(team_access)
    if not active_tasks:
        return task
    current_task = active_tasks[0]
    if current_task.id == task.id:
        return current_task
    raise ActiveCodexTaskConflict(current_task)


def codex_activity_sort_key(task: TaskRecord) -> tuple[int, float, float]:
    status_priority = CODEX_ACTIVITY_STATUS_PRIORITY.get(status_value(task.status), 9)
    created_at = timestamp_value(task.created_at)
    updated_at = timestamp_value(task.updated_at)
    return (status_priority, -created_at, -updated_at)


def timestamp_value(value: object) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return 0.0
