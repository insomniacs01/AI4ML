from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_progress_store import read_progress_events
from backend.app.services.task_runtime_progress_events import (
    write_codex_plan_approved_progress,
    write_codex_resume_progress,
)


def _task(status: TaskStatus) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-runtime-progress",
        team_id="team-1",
        created_by="user-1",
        name="Runtime Progress Task",
        description="Record Codex progress events.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_write_codex_resume_progress_preserves_existing_explicit_percent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    (output / "progress.json").write_text(
        json.dumps({"status": "interrupted", "percent": 64, "percent_source": "codex_runtime"}),
        encoding="utf-8",
    )
    task = _task(TaskStatus.paused_for_review)
    task.codex_workspace_path = str(workspace)

    write_codex_resume_progress(task)

    payload = json.loads((output / "progress.json").read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["percent"] == 64
    assert payload["percent_source"] == "codex_runtime"
    assert read_progress_events(workspace)[-1]["event"] == "resume_requested"


def test_write_codex_plan_approved_progress_records_event_without_inferred_percent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "output").mkdir(parents=True)
    task = _task(TaskStatus.paused_for_review)
    task.codex_workspace_path = str(workspace)

    write_codex_plan_approved_progress(task)

    payload = json.loads((workspace / "output" / "progress.json").read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["schema_version"] == "ai4ml-progress-v1"
    assert payload["events_path"] == "state/progress_events.jsonl"
    assert "percent" not in payload
    assert "percent_source" not in payload
    events = read_progress_events(workspace)
    assert events[-1]["event"] == "plan_approved"
    assert events[-1]["evidence"] == ["output/plan.md"]
