from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_human_stage_blueprints import get_previous_status


def _task(status: TaskStatus = TaskStatus.paused_for_review) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-human-stage-blueprints",
        team_id="team-1",
        created_by="user-1",
        name="Human stage blueprints",
        description="Resolve previous task status.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_get_previous_status_uses_human_loop_previous_status() -> None:
    task = _task()
    task.structured_requirements = {"human_loop": {"previous_status": "planning"}}

    assert get_previous_status(task) == TaskStatus.planning


def test_get_previous_status_ignores_paused_previous_status_and_falls_back_to_run_state() -> None:
    task = _task()
    task.last_run_attempt = RunAttempt(output_dir="failed-run")
    task.structured_requirements = {"human_loop": {"previous_status": "paused_for_review"}}

    assert get_previous_status(task) == TaskStatus.failed


def test_get_previous_status_uses_rerun_requested_dataset_state() -> None:
    task = _task()
    task.dataset_filename = "train.csv"
    task.last_run = RunSummary(best_model="ridge", metric_name="mae", metric_value=2.0, output_dir="run")
    task.structured_requirements = {"human_loop": {"rerun_requested": True}}

    assert get_previous_status(task) == TaskStatus.uploaded
