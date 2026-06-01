from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_backend import build_codex_run_progress, sync_task_from_codex_artifacts
from backend.app.services.quota_runtime_guard import (
    pause_codex_task_for_quota,
    pause_member_tasks_for_quota,
    quota_is_exhausted,
    quota_token_budget,
)


def _task() -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Task",
        description="Run model",
        status=TaskStatus.running,
        executor_type="codex",
        codex_session_id="session-1",
        codex_status="running",
        created_at=now,
        updated_at=now,
    )


def test_quota_exhausted_when_remaining_is_zero() -> None:
    quota = SimpleNamespace(status="active", token_quota=100, token_remaining=0)

    assert quota_is_exhausted(quota)
    assert quota_token_budget(quota) == 0


def test_quota_guard_pauses_running_codex_task(monkeypatch) -> None:
    task = _task()
    store = SimpleNamespace(save_task=Mock(side_effect=lambda saved_task, access_token: saved_task))
    team_access = SimpleNamespace(access_token="token")
    interrupted = Mock()
    monkeypatch.setattr("backend.app.services.quota_runtime_guard.interrupt_codex_task", interrupted)

    result = pause_codex_task_for_quota(store, task, team_access)

    interrupted.assert_called_once()
    store.save_task.assert_called_once()
    assert result.status == TaskStatus.paused_for_review
    assert result.codex_status == "interrupted"
    assert "额度已用完" in (result.notes or "")
    assert result.structured_requirements["quota_guard"]["reason"] == "member_token_quota_exhausted"


def test_quota_guard_marks_paused_task_without_reinterrupting(monkeypatch) -> None:
    task = _task()
    task.status = TaskStatus.paused_for_review
    task.codex_status = "interrupted"
    store = SimpleNamespace(save_task=Mock(side_effect=lambda saved_task, access_token: saved_task))
    team_access = SimpleNamespace(access_token="token")
    interrupted = Mock()
    monkeypatch.setattr("backend.app.services.quota_runtime_guard.interrupt_codex_task", interrupted)

    result = pause_codex_task_for_quota(store, task, team_access)

    interrupted.assert_not_called()
    store.save_task.assert_called_once()
    assert result.status == TaskStatus.paused_for_review
    assert result.structured_requirements["quota_guard"]["status"] == "exhausted"


def test_pause_member_tasks_for_quota_only_guards_target_member_codex_tasks(monkeypatch) -> None:
    target_running = _task()
    target_running.id = "target-running"
    target_running.created_by = "user-1"
    target_paused = _task()
    target_paused.id = "target-paused"
    target_paused.status = TaskStatus.paused_for_review
    target_paused.codex_status = "interrupted"
    target_paused.created_by = "user-1"
    other_user = _task()
    other_user.id = "other-user"
    other_user.created_by = "user-2"
    non_codex = _task()
    non_codex.id = "non-codex"
    non_codex.executor_type = "legacy"
    saved = []
    store = SimpleNamespace(
        list_tasks=Mock(return_value=[target_running, target_paused, other_user, non_codex]),
        save_task=Mock(side_effect=lambda task, access_token: saved.append(task) or task),
    )
    team_access = SimpleNamespace(team_id="team-1", access_token="token")
    monkeypatch.setattr("backend.app.services.quota_runtime_guard.interrupt_codex_task", Mock())

    result = pause_member_tasks_for_quota(store, team_access, user_id="user-1")

    assert [task.id for task in result] == ["target-running", "target-paused"]
    assert [task.id for task in saved] == ["target-running", "target-paused"]
    assert all(task.structured_requirements["quota_guard"]["reason"] == "member_token_quota_exhausted" for task in result)


def test_quota_guard_prevents_stale_running_progress_from_resuming_task(tmp_path) -> None:
    task = _task()
    task.status = TaskStatus.paused_for_review
    task.structured_requirements = {
        "quota_guard": {
            "status": "exhausted",
            "reason": "member_token_quota_exhausted",
        }
    }
    workspace_root = tmp_path / "workspaces"
    workspace = workspace_root / "ai4ml-task-1"
    (workspace / "output").mkdir(parents=True)
    (workspace / "output" / "progress.json").write_text('{"status":"running"}', encoding="utf-8")
    task.codex_workspace_path = str(workspace)
    settings = SimpleNamespace(codex_workspace_root=workspace_root, storage_dir=tmp_path / "tasks")

    synced_task, _artifacts = sync_task_from_codex_artifacts(task, settings)

    assert synced_task.status == TaskStatus.paused_for_review
    assert synced_task.codex_status == "interrupted"


def test_completed_codex_artifacts_override_stale_running_progress(tmp_path) -> None:
    task = _task()
    workspace_root = tmp_path / "workspaces"
    workspace = workspace_root / "ai4ml-task-1"
    output = workspace / "output"
    output.mkdir(parents=True)
    (output / "progress.json").write_text(
        '{"status":"running","percent":28,"summary":"still running","steps":[{"status":"completed"},{"status":"running"},{"status":"pending"}]}',
        encoding="utf-8",
    )
    (output / "metrics.json").write_text(
        '{"best_model":{"name":"ridge","test":{"signed_log_mae":0.42}},"models":{"ridge":{"test":{"signed_log_mae":0.42}}}}',
        encoding="utf-8",
    )
    (output / "report.md").write_text("# Report\n", encoding="utf-8")
    (output / "predict.py").write_text("print('ok')\n", encoding="utf-8")
    task.codex_workspace_path = str(workspace)
    settings = SimpleNamespace(codex_workspace_root=workspace_root, storage_dir=tmp_path / "tasks")

    synced_task, _artifacts = sync_task_from_codex_artifacts(task, settings)
    progress = build_codex_run_progress(synced_task, settings)

    assert synced_task.status == TaskStatus.completed
    assert synced_task.codex_status == "completed"
    assert synced_task.last_run is not None
    assert synced_task.last_run.best_model == "ridge"
    assert synced_task.last_run.metric_name == "signed_log_mae"
    assert synced_task.last_run.metric_value == 0.42
    assert progress.status == "completed"
    assert progress.progress_percent == 100
