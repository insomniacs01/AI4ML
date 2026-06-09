from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.api.routes import task_artifacts as task_artifact_routes
from backend.app.models.task import (
    RunAttempt,
    RunSummary,
    TaskCodeWorkspaceResponse,
    TaskModelReportResponse,
    TaskPredictionDemoRequest,
    TaskPredictionDemoResponse,
    TaskRecord,
    TaskStatus,
)
from backend.app.services.task_output_resolution import resolve_task_output_dir


def _task(*, updated_at: datetime | None = None) -> TaskRecord:
    now = updated_at or datetime.now(timezone.utc)
    return TaskRecord(
        id="task-artifacts",
        team_id="team-1",
        created_by="user-1",
        name="Artifact Task",
        description="Resolve artifact output directory.",
        status=TaskStatus.running,
        created_at=now,
        updated_at=now,
    )


def test_resolve_task_output_dir_prefers_successful_run_when_requested(tmp_path: Path) -> None:
    success_dir = tmp_path / "success"
    attempt_dir = tmp_path / "attempt"
    success_dir.mkdir()
    attempt_dir.mkdir()
    task = _task()
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir=str(success_dir),
    )
    task.last_run_attempt = RunAttempt(output_dir=str(attempt_dir))

    requested, resolved = resolve_task_output_dir(task, prefer_success=True)

    assert requested == success_dir
    assert resolved == success_dir


def test_resolve_task_output_dir_rejects_stale_current_attempt(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    old_timestamp = (now - timedelta(hours=1)).timestamp()
    os.utime(attempt_dir, (old_timestamp, old_timestamp))
    task = _task(updated_at=now)
    task.last_run_attempt = RunAttempt(output_dir=str(attempt_dir))

    requested, resolved = resolve_task_output_dir(
        task,
        require_current_running=True,
        current_attempt_started_at=now,
    )

    assert requested == attempt_dir
    assert resolved is None


def test_resolve_task_output_dir_discovers_latest_candidate_root_child(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    task_root = run_root / "task-artifacts"
    older = task_root / "run-older"
    newer = task_root / "run-newer"
    older.mkdir(parents=True)
    newer.mkdir()
    older_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()
    os.utime(older, (older_timestamp, older_timestamp))
    settings = SimpleNamespace(run_output_dir=run_root, codex_workspace_root=None)

    _requested, resolved = resolve_task_output_dir(
        _task(),
        settings=settings,
        include_candidate_roots=True,
    )

    assert resolved == newer


def test_report_route_uses_cached_codex_report_without_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task()
    get_task_calls: list[dict[str, object]] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, **kwargs: object) -> TaskRecord | None:
            get_task_calls.append({"team_id": team_id, "task_id": task_id, **kwargs})
            return task

    def fail_if_synced(*args: object, **kwargs: object) -> None:
        raise AssertionError("report route must not sync Codex task state")

    report = TaskModelReportResponse(
        task_id=task.id,
        task_name=task.name,
        generated_at=task.updated_at,
    )

    monkeypatch.setattr(task_artifact_routes, "get_task_store", lambda: Store())
    monkeypatch.setattr(task_artifact_routes, "get_settings", lambda: object())
    monkeypatch.setattr(task_artifact_routes, "is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr(task_artifact_routes, "sync_codex_task_state", fail_if_synced)
    monkeypatch.setattr(
        task_artifact_routes,
        "build_codex_task_model_report",
        lambda task_arg, **kwargs: report,
    )
    monkeypatch.setattr(task_artifact_routes, "build_task_model_report", fail_if_synced)

    result = task_artifact_routes.get_task_model_report(
        task.id,
        SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert result is report
    assert get_task_calls == [
        {
            "team_id": task.team_id,
            "task_id": task.id,
            "access_token": "token",
            "allow_stale_cache": True,
        }
    ]


def test_codex_plan_route_reads_known_workspace_without_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    task.executor_type = "codex"
    workspace = tmp_path / "workspace"
    plan_path = workspace / "output" / "plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("# Plan\n\nUse the known workspace.", encoding="utf-8")
    task.codex_workspace_path = str(workspace)
    get_task_calls: list[dict[str, object]] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, **kwargs: object) -> TaskRecord | None:
            get_task_calls.append({"team_id": team_id, "task_id": task_id, **kwargs})
            return task

    def fail_if_synced(*args: object, **kwargs: object) -> None:
        raise AssertionError("codex plan route must not sync Codex task state")

    monkeypatch.setattr(task_artifact_routes, "get_task_store", lambda: Store())
    monkeypatch.setattr(task_artifact_routes, "get_settings", lambda: SimpleNamespace(codex_workspace_root=tmp_path))
    monkeypatch.setattr(task_artifact_routes, "sync_codex_task_state", fail_if_synced)

    result = task_artifact_routes.get_task_codex_plan(
        task.id,
        SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert result.available is True
    assert result.plan_text == "# Plan\n\nUse the known workspace."
    assert result.workspace_path == str(workspace)
    assert get_task_calls == [
        {
            "team_id": task.team_id,
            "task_id": task.id,
            "access_token": "token",
            "allow_stale_cache": True,
        }
    ]


def test_report_route_falls_back_to_full_task_when_codex_report_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    cached_task = _task()
    full_task = _task()
    full_task.name = "Full detail task"
    get_task_calls: list[dict[str, object]] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, **kwargs: object) -> TaskRecord | None:
            get_task_calls.append({"team_id": team_id, "task_id": task_id, **kwargs})
            return cached_task if kwargs.get("allow_stale_cache") else full_task

    report = TaskModelReportResponse(
        task_id=full_task.id,
        task_name=full_task.name,
        generated_at=full_task.updated_at,
    )

    monkeypatch.setattr(task_artifact_routes, "get_task_store", lambda: Store())
    monkeypatch.setattr(task_artifact_routes, "get_settings", lambda: object())
    monkeypatch.setattr(task_artifact_routes, "is_codex_task", lambda task_arg, settings: False)
    monkeypatch.setattr(task_artifact_routes, "build_codex_task_model_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_artifact_routes, "build_task_model_report", lambda task_arg: report)

    result = task_artifact_routes.get_task_model_report(
        full_task.id,
        SimpleNamespace(team_id=full_task.team_id, access_token="token"),
    )

    assert result is report
    assert get_task_calls == [
        {
            "team_id": full_task.team_id,
            "task_id": full_task.id,
            "access_token": "token",
            "allow_stale_cache": True,
        },
        {
            "team_id": full_task.team_id,
            "task_id": full_task.id,
            "access_token": "token",
        },
    ]


def test_report_route_falls_back_to_full_task_for_codex_task_without_report_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    task.name = "Codex fallback task"
    get_task_calls: list[dict[str, object]] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, **kwargs: object) -> TaskRecord | None:
            get_task_calls.append({"team_id": team_id, "task_id": task_id, **kwargs})
            return task

    report = TaskModelReportResponse(
        task_id=task.id,
        task_name=task.name,
        generated_at=task.updated_at,
        report_markdown="# Fallback report",
    )

    monkeypatch.setattr(task_artifact_routes, "get_task_store", lambda: Store())
    monkeypatch.setattr(task_artifact_routes, "get_settings", lambda: object())
    monkeypatch.setattr(task_artifact_routes, "is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr(task_artifact_routes, "build_codex_task_model_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_artifact_routes, "build_task_model_report", lambda task_arg: report)

    result = task_artifact_routes.get_task_model_report(
        task.id,
        SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert result is report
    assert get_task_calls == [
        {
            "team_id": task.team_id,
            "task_id": task.id,
            "access_token": "token",
            "allow_stale_cache": True,
        }
    ]


def test_prediction_demo_route_does_not_sync_codex_state(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task()
    get_task_calls: list[dict[str, object]] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, **kwargs: object) -> TaskRecord | None:
            get_task_calls.append({"team_id": team_id, "task_id": task_id, **kwargs})
            return task

    def fail_if_synced(*args: object, **kwargs: object) -> None:
        raise AssertionError("prediction demo route must not sync Codex task state")

    response = TaskPredictionDemoResponse(
        task_id=task.id,
        supported=False,
        detail="stub",
    )

    monkeypatch.setattr(task_artifact_routes, "get_task_store", lambda: Store())
    monkeypatch.setattr(task_artifact_routes, "sync_codex_task_state", fail_if_synced)
    monkeypatch.setattr(task_artifact_routes, "build_prediction_demo_response", lambda task_arg, payload: response)

    result = task_artifact_routes.run_task_prediction_demo(
        task.id,
        TaskPredictionDemoRequest(features={}),
        SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert result is response
    assert get_task_calls == [
        {
            "team_id": task.team_id,
            "task_id": task.id,
            "access_token": "token",
        }
    ]


def test_code_workspace_route_does_not_sync_codex_state(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task()
    get_task_calls: list[dict[str, object]] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, **kwargs: object) -> TaskRecord | None:
            get_task_calls.append({"team_id": team_id, "task_id": task_id, **kwargs})
            return task

    def fail_if_synced(*args: object, **kwargs: object) -> None:
        raise AssertionError("code workspace route must not sync Codex task state")

    response = TaskCodeWorkspaceResponse(task_id=task.id, task_name=task.name)

    monkeypatch.setattr(task_artifact_routes, "get_task_store", lambda: Store())
    monkeypatch.setattr(task_artifact_routes, "sync_codex_task_state", fail_if_synced)
    monkeypatch.setattr(task_artifact_routes, "build_task_code_workspace", lambda task_arg: response)

    result = task_artifact_routes.get_task_code_workspace(
        task.id,
        SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert result is response
    assert get_task_calls == [
        {
            "team_id": task.team_id,
            "task_id": task.id,
            "access_token": "token",
        }
    ]
