from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_backend import build_codex_run_progress, sync_task_from_codex_artifacts


def _task() -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Codex Task",
        description="Run Codex workflow.",
        status=TaskStatus.running,
        executor_type="codex",
        created_at=now,
        updated_at=now,
    )


def _workspace(tmp_path: Path, progress: dict) -> Path:
    workspace = tmp_path / "workspaces" / "ai4ml-task-1"
    (workspace / "input").mkdir(parents=True)
    (workspace / "output").mkdir()
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({"authoritative_inputs": {"task_id": "task-1"}}),
        encoding="utf-8",
    )
    (workspace / "output" / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    return workspace


def _settings(tmp_path: Path):
    return SimpleNamespace(codex_workspace_root=tmp_path / "workspaces", storage_dir=tmp_path / "tasks")


def test_codex_sync_waiting_status_pauses_for_plan_review(tmp_path: Path) -> None:
    _workspace(tmp_path, {"status": "plan_ready"})

    synced_task, _artifacts = sync_task_from_codex_artifacts(_task(), _settings(tmp_path))

    assert synced_task.status == TaskStatus.paused_for_review
    assert synced_task.codex_status == "plan_ready"
    assert synced_task.notes == "Codex 已生成建模计划，等待人工确认后继续执行。"
    assert synced_task.structured_requirements["human_loop"]["previous_status"] == TaskStatus.running.value
    assert synced_task.structured_requirements["human_loop"]["manual_hold"] is False
    assert synced_task.structured_requirements["codex"]["status"] == "plan_ready"


def test_codex_sync_failed_status_records_failed_attempt(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"status": "failed", "summary": "training crashed"})

    synced_task, _artifacts = sync_task_from_codex_artifacts(_task(), _settings(tmp_path))

    assert synced_task.status == TaskStatus.failed
    assert synced_task.codex_status == "failed"
    assert synced_task.codex_finished_at is not None
    assert synced_task.last_run_attempt is not None
    assert synced_task.last_run_attempt.output_dir == str(workspace)
    assert synced_task.last_run_attempt.diagnosis == "Codex task did not complete successfully."
    assert synced_task.last_run_attempt.diagnosis_detail == "training crashed"
    assert synced_task.notes == "training crashed"
    assert synced_task.structured_requirements["codex"]["status"] == "failed"


def test_codex_failed_progress_is_not_reported_as_completed(tmp_path: Path) -> None:
    _workspace(tmp_path, {
        "status": "failed",
        "percent": 100,
        "summary": "training crashed",
        "steps": [{"status": "completed"}, {"status": "failed"}],
    })
    settings = _settings(tmp_path)

    synced_task, _artifacts = sync_task_from_codex_artifacts(_task(), settings)
    progress = build_codex_run_progress(synced_task, settings)

    assert synced_task.status == TaskStatus.failed
    assert progress.status == "failed"
    assert progress.progress_percent == 99


def test_codex_sync_interrupted_status_is_recoverable_pause(tmp_path: Path) -> None:
    _workspace(tmp_path, {"status": "interrupted", "summary": "process stopped"})

    synced_task, _artifacts = sync_task_from_codex_artifacts(_task(), _settings(tmp_path))

    assert synced_task.status == TaskStatus.paused_for_review
    assert synced_task.codex_status == "interrupted"
    assert synced_task.notes == "process stopped"


def test_codex_sync_interrupted_status_preserves_cancelled_task(tmp_path: Path) -> None:
    _workspace(tmp_path, {"status": "interrupted", "summary": "user cancelled"})
    task = _task()
    task.status = TaskStatus.cancelled
    task.notes = "用户已取消任务。"

    synced_task, _artifacts = sync_task_from_codex_artifacts(task, _settings(tmp_path))

    assert synced_task.status == TaskStatus.cancelled
    assert synced_task.codex_status == "interrupted"
    assert synced_task.notes == "用户已取消任务。"
