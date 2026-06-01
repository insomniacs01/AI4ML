from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.models.governance import PlatformLimitsRecord
from backend.app.models.task import TaskRecord


PLATFORM_LIMITS_FILENAME = "platform_limits.json"
DEFAULT_PLATFORM_LIMITS = PlatformLimitsRecord()
ACTIVE_TASK_STATUSES = {"running"}
WAITING_START_TASK_STATUSES = {"uploaded", "planning"}


class PlatformLimitError(RuntimeError):
    pass


def read_platform_limits(settings: Settings) -> PlatformLimitsRecord:
    path = _limits_path(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PLATFORM_LIMITS.model_copy()
    if not isinstance(payload, dict):
        return DEFAULT_PLATFORM_LIMITS.model_copy()
    return PlatformLimitsRecord(**payload)


def save_platform_limits(settings: Settings, payload: PlatformLimitsRecord) -> PlatformLimitsRecord:
    path = _limits_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)
    return payload


def assert_user_can_create_task(settings: Settings, *, tasks: list[TaskRecord], user_id: str) -> None:
    limits = read_platform_limits(settings)
    if limits.max_queued_tasks_per_user <= 0:
        return
    waiting_start_count = _count_tasks_for_user(tasks, user_id, statuses=WAITING_START_TASK_STATUSES)
    if waiting_start_count >= limits.max_queued_tasks_per_user:
        raise PlatformLimitError(
            f"当前用户待启动任务数已达到上限 {limits.max_queued_tasks_per_user}，请先处理或删除已有任务。"
        )


def assert_user_can_start_task(
    settings: Settings,
    *,
    tasks: list[TaskRecord],
    user_id: str,
    task_id: str,
) -> None:
    limits = read_platform_limits(settings)
    if limits.max_concurrent_tasks_per_user > 0:
        active_count = _count_tasks_for_user(
            tasks,
            user_id,
            statuses=ACTIVE_TASK_STATUSES,
            excluded_task_id=task_id,
        )
        if active_count >= limits.max_concurrent_tasks_per_user:
            raise PlatformLimitError(
                f"当前用户同时运行任务数已达到上限 {limits.max_concurrent_tasks_per_user}，请等待已有任务完成。"
            )


def assert_time_budget_within_limit(settings: Settings, time_limit: int | None) -> None:
    limits = read_platform_limits(settings)
    if time_limit is None or limits.max_task_time_budget_s <= 0:
        return
    if time_limit > limits.max_task_time_budget_s:
        raise PlatformLimitError(
            f"训练预算 {time_limit} 秒超过管理员设置的最大值 {limits.max_task_time_budget_s} 秒。"
        )


def _limits_path(settings: Settings) -> Path:
    return Path(settings.storage_dir).parent / PLATFORM_LIMITS_FILENAME


def _count_tasks_for_user(
    tasks: list[TaskRecord],
    user_id: str,
    *,
    statuses: set[str],
    excluded_task_id: str | None = None,
) -> int:
    return sum(
        1
        for task in tasks
        if task.id != excluded_task_id
        and _task_creator(task) == user_id
        and _status_value(task.status) in statuses
    )


def _task_creator(task: TaskRecord) -> str:
    return task.creator_user_id or task.created_by


def _status_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value or "")
