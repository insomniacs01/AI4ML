from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_codex_runtime_snapshot_sync import sync_codex_runtime_snapshot


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-codex-runtime-sync",
        team_id="team-1",
        created_by="user-1",
        name="Codex runtime sync",
        description="Runtime sync task.",
        status=TaskStatus.running,
        executor_type="codex",
        created_at=now,
        updated_at=now,
    )


def _team_access():
    return SimpleNamespace(access_token="token", user=SimpleNamespace(id="user-1"))


def test_sync_codex_runtime_snapshot_creates_plan_request_for_blocked_progress(monkeypatch) -> None:
    task = _task()
    progress = SimpleNamespace(status="blocked")
    plan_requests = []
    improvement_requests = []

    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.sync_codex_task_state",
        lambda task_arg, settings, **kwargs: (task_arg, {"progress": {"status": "plan_ready"}}),
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.build_codex_run_progress",
        lambda task_arg, settings: progress,
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.build_codex_overview",
        lambda task_arg, settings: {"summary": "overview"},
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.sync_codex_token_ledger",
        lambda task_store, task_arg, team_access: False,
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.ensure_codex_plan_request",
        lambda task_arg, team_access: plan_requests.append(task_arg.id),
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.ensure_codex_improvement_request",
        lambda task_arg, team_access, artifacts: improvement_requests.append(task_arg.id),
    )

    synced_task, progress_response, overview, artifacts = sync_codex_runtime_snapshot(
        object(),
        task,
        _team_access(),
        object(),
    )

    assert synced_task is task
    assert progress_response is progress
    assert overview == {"summary": "overview"}
    assert artifacts == {"progress": {"status": "plan_ready"}}
    assert plan_requests == [task.id]
    assert improvement_requests == []


def test_sync_codex_runtime_snapshot_creates_improvement_request_for_improvement_artifacts(monkeypatch) -> None:
    task = _task()
    progress = SimpleNamespace(status="blocked")
    plan_requests = []
    improvement_requests = []

    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.sync_codex_task_state",
        lambda task_arg, settings, **kwargs: (task_arg, {"improvement_plan": "Improve validation."}),
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.build_codex_run_progress",
        lambda task_arg, settings: progress,
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.build_codex_overview",
        lambda task_arg, settings: {},
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.sync_codex_token_ledger",
        lambda task_store, task_arg, team_access: False,
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.ensure_codex_plan_request",
        lambda task_arg, team_access: plan_requests.append(task_arg.id),
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_snapshot_sync.ensure_codex_improvement_request",
        lambda task_arg, team_access, artifacts: improvement_requests.append(artifacts["improvement_plan"]),
    )

    sync_codex_runtime_snapshot(object(), task, _team_access(), object())

    assert plan_requests == []
    assert improvement_requests == ["Improve validation."]
