from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.models.governance import PlatformLimitsRecord
from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.platform_limits import (
    PlatformLimitError,
    assert_time_budget_within_limit,
    assert_user_can_create_task,
    assert_user_can_start_task,
    save_platform_limits,
)


def test_platform_limits_block_excess_queued_tasks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_platform_limits(settings, PlatformLimitsRecord(max_queued_tasks_per_user=1))
    tasks = [_task("task-1", status=TaskStatus.uploaded)]

    with pytest.raises(PlatformLimitError, match="待启动任务数已达到上限"):
        assert_user_can_create_task(settings, tasks=tasks, user_id="user-1")


def test_platform_limits_block_excess_running_tasks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_platform_limits(settings, PlatformLimitsRecord(max_concurrent_tasks_per_user=1))
    tasks = [_task("task-1", status=TaskStatus.running), _task("task-2", status=TaskStatus.uploaded)]

    with pytest.raises(PlatformLimitError, match="同时运行任务数已达到上限"):
        assert_user_can_start_task(settings, tasks=tasks, user_id="user-1", task_id="task-2")


def test_platform_limits_ignore_current_running_task(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_platform_limits(settings, PlatformLimitsRecord(max_concurrent_tasks_per_user=1))
    tasks = [_task("task-1", status=TaskStatus.running)]

    assert_user_can_start_task(settings, tasks=tasks, user_id="user-1", task_id="task-1")


def test_platform_limits_ignore_paused_and_human_waiting_tasks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_platform_limits(settings, PlatformLimitsRecord(max_concurrent_tasks_per_user=1))
    tasks = [
        _task("task-1", status=TaskStatus.paused_for_review),
        _task("task-2", status=TaskStatus.waiting_human),
    ]

    assert_user_can_start_task(settings, tasks=tasks, user_id="user-1", task_id="task-3")


def test_platform_limits_block_excess_time_budget(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_platform_limits(settings, PlatformLimitsRecord(max_task_time_budget_s=60))

    with pytest.raises(PlatformLimitError, match="超过管理员设置的最大值"):
        assert_time_budget_within_limit(settings, 120)


def _settings(tmp_path: Path) -> Settings:
    return Settings(storage_dir=tmp_path / "storage" / "tasks")


def _task(task_id: str, *, status: TaskStatus, created_by: str = "user-1") -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id=task_id,
        team_id="team-1",
        created_by=created_by,
        creator_user_id=created_by,
        name=task_id,
        description="Task",
        status=status,
        created_at=now,
        updated_at=now,
    )
