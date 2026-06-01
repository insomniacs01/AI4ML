from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_runtime_activity import is_active_codex_task, sync_codex_activity_candidate


def _task(status: TaskStatus, *, codex_status: str | None = None) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id=f"task-{status.value}",
        team_id="team-1",
        created_by="user-1",
        name="Codex task",
        description="Task",
        status=status,
        executor_type="codex",
        codex_workspace_path="workspace",
        codex_status=codex_status,
        created_at=now,
        updated_at=now,
    )


def test_paused_and_human_waiting_tasks_do_not_block_codex_activity() -> None:
    assert not is_active_codex_task(_task(TaskStatus.paused_for_review, codex_status="interrupted"))
    assert not is_active_codex_task(_task(TaskStatus.waiting_human, codex_status="waiting_plan_approval"))
    assert not is_active_codex_task(_task(TaskStatus.paused_for_review, codex_status="running"))


def test_running_codex_task_blocks_codex_activity() -> None:
    assert is_active_codex_task(_task(TaskStatus.running, codex_status="running"))


def test_starting_backend_status_blocks_codex_activity_for_non_paused_task() -> None:
    assert is_active_codex_task(_task(TaskStatus.planning, codex_status="starting"))


def test_activity_candidate_sync_does_not_promote_paused_task(monkeypatch) -> None:
    task = _task(TaskStatus.paused_for_review, codex_status="interrupted")
    monkeypatch.setattr(
        "backend.app.services.task_runtime_activity.sync_codex_task_state",
        lambda *args, **kwargs: (_raise_assertion("paused tasks should not be synced for activity conflicts"), {}),
    )

    synced = sync_codex_activity_candidate(task, SimpleNamespace(access_token="token"))

    assert synced.status == TaskStatus.paused_for_review


def _raise_assertion(message: str) -> None:
    raise AssertionError(message)
