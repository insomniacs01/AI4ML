from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.core.config import Settings
from backend.app.core.supabase_auth import SupabaseUser, TeamAccessContext
from backend.app.models.governance import PlatformLimitsRecord
from backend.app.models.task import TaskRecord, TaskRunRequest, TaskStatus
from backend.app.services.platform_limits import PlatformLimitError, save_platform_limits
from backend.app.services.task_run_preflight import (
    assert_task_run_preflight,
    task_requested_time_limit,
)


class _FakeTaskStore:
    def __init__(self, tasks: list[TaskRecord]) -> None:
        self.tasks = tasks
        self.calls: list[dict] = []

    def list_tasks(self, team_id: str, **kwargs) -> list[TaskRecord]:
        self.calls.append({"team_id": team_id, **kwargs})
        return self.tasks


def test_task_requested_time_limit_prefers_explicit_payload_value() -> None:
    task = _task(
        "task-1",
        structured_requirements={"training_constraints": {"time_limit": 90}},
    )

    assert task_requested_time_limit(task, TaskRunRequest(time_limit=30)) == 30
    assert task_requested_time_limit(task, TaskRunRequest()) == 90


def test_task_run_preflight_reads_uncached_tasks_for_platform_limits(tmp_path: Path) -> None:
    task = _task("task-1")
    store = _FakeTaskStore([task])

    assert_task_run_preflight(
        store,
        task,
        TaskRunRequest(),
        _team_access(),
        settings=_settings(tmp_path),
    )

    assert store.calls == [
        {
            "team_id": "team-1",
            "access_token": "token-1",
            "lightweight": True,
            "prefer_cache": False,
        }
    ]


def test_task_run_preflight_enforces_resolved_time_budget(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    save_platform_limits(settings, PlatformLimitsRecord(max_task_time_budget_s=20))
    task = _task(
        "task-1",
        structured_requirements={"training_constraints": {"time_limit": 45}},
    )

    with pytest.raises(PlatformLimitError, match="超过管理员设置的最大值"):
        assert_task_run_preflight(_FakeTaskStore([task]), task, TaskRunRequest(), _team_access(), settings=settings)


def _settings(tmp_path: Path) -> Settings:
    return Settings(storage_dir=tmp_path / "storage" / "tasks")


def _team_access() -> TeamAccessContext:
    return TeamAccessContext(
        team_id="team-1",
        role="admin",
        user=SupabaseUser(id="user-1", email=None, raw={}),
        access_token="token-1",
    )


def _task(
    task_id: str,
    *,
    structured_requirements: dict | None = None,
) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id=task_id,
        team_id="team-1",
        created_by="user-1",
        creator_user_id="user-1",
        name=task_id,
        description="Task",
        status=TaskStatus.uploaded,
        structured_requirements=structured_requirements,
        created_at=now,
        updated_at=now,
    )
