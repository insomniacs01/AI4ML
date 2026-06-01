from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_artifacts import resolve_task_output_dir


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
