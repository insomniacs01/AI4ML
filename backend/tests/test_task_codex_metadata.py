from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_codex_metadata import update_codex_structured_metadata


def _task(**overrides: object) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = {
        "id": "task-codex-metadata",
        "team_id": "team-1",
        "created_by": "user-1",
        "name": "Codex metadata",
        "description": "Metadata task.",
        "status": TaskStatus.running,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return TaskRecord(**payload)


def test_update_codex_structured_metadata_initializes_requirements() -> None:
    started_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    finished_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    task = _task(
        codex_workspace_path="workspace-1",
        codex_session_id="session-1",
        codex_thread_id="thread-1",
        codex_status="running",
        codex_started_at=started_at,
        codex_finished_at=finished_at,
    )

    updated = update_codex_structured_metadata(task)

    assert updated.structured_requirements == {
        "executor_type": "codex",
        "codex": {
            "workspace_path": "workspace-1",
            "session_id": "session-1",
            "thread_id": "thread-1",
            "status": "running",
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        },
    }


def test_update_codex_structured_metadata_preserves_existing_codex_fields() -> None:
    task = _task(
        structured_requirements={
            "metric_name": "accuracy",
            "codex": {
                "custom": "kept",
                "status": "old-status",
            },
        },
        codex_status="completed",
    )

    updated = update_codex_structured_metadata(task)

    assert updated.structured_requirements["metric_name"] == "accuracy"
    assert updated.structured_requirements["executor_type"] == "codex"
    assert updated.structured_requirements["codex"]["custom"] == "kept"
    assert updated.structured_requirements["codex"]["status"] == "completed"
