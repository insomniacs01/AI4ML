from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_progress_percent import ProgressPercentResult, codex_progress_percent


def _task(status: TaskStatus = TaskStatus.running) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Codex Progress Task",
        description="Read Codex progress.",
        status=status,
        executor_type="codex",
        created_at=now,
        updated_at=now,
    )


def _completed_artifacts() -> dict:
    return {
        "report": {"exists": True},
        "predict": {"exists": True},
        "metrics": {"selected_model": {"name": "ridge"}},
    }


def test_completed_status_or_artifacts_returns_completed_percent() -> None:
    assert codex_progress_percent(_task(), {}, "completed", {}) == ProgressPercentResult(100, "completed", None)
    assert codex_progress_percent(_task(), {}, "running", _completed_artifacts()) == ProgressPercentResult(
        100,
        "completed",
        None,
    )


def test_failed_acceptance_never_returns_completed_percent() -> None:
    artifacts = {
        "report": {"exists": True},
        "predict": {"exists": True},
        "metrics": {"acceptance": {"passed": False}},
    }

    assert codex_progress_percent(_task(), {"percent": 100}, "completed", artifacts) == ProgressPercentResult(
        99,
        "progress_json_percent",
        None,
    )
    assert codex_progress_percent(_task(), {}, "completed", artifacts) == ProgressPercentResult(
        None,
        None,
        "workspace_not_ready",
    )


def test_stop_and_report_partial_result_returns_completed_percent() -> None:
    artifacts = {
        "progress": {"status": "partial", "current_step": "stop_and_report_completed"},
        "report": {"exists": True},
        "predict": {"exists": True},
        "metrics": {"acceptance": {"passed": False}},
    }

    assert codex_progress_percent(_task(), {}, "partial", artifacts) == ProgressPercentResult(
        100,
        "completed",
        None,
    )


def test_not_started_task_statuses_return_zero_without_reading_progress() -> None:
    for status in (TaskStatus.draft, TaskStatus.uploaded, TaskStatus.planning):
        assert codex_progress_percent(_task(status), {"percent": 80}, "running", {}) == ProgressPercentResult(
            0,
            "not_started",
            None,
        )


def test_explicit_progress_percent_uses_declared_source_and_clamps_before_completion() -> None:
    assert codex_progress_percent(
        _task(),
        {"progress_percent": "42"},
        "running",
        {},
    ) == ProgressPercentResult(42, "progress_json_progress_percent", None)
    assert codex_progress_percent(
        _task(),
        {"percent": 150, "percent_source": "codex_event"},
        "running",
        {},
    ) == ProgressPercentResult(99, "codex_event", None)


def test_failed_and_interrupted_progress_keep_explicit_percent_but_never_complete() -> None:
    assert codex_progress_percent(
        _task(TaskStatus.failed),
        {"percent": 100},
        "failed",
        {},
    ) == ProgressPercentResult(99, "progress_json_percent", None)
    assert codex_progress_percent(
        _task(TaskStatus.paused_for_review),
        {"percent": -5},
        "interrupted",
        {},
    ) == ProgressPercentResult(0, "progress_json_percent", None)


def test_progress_unavailable_reason_reports_progress_file_state_first() -> None:
    assert codex_progress_percent(
        _task(),
        {},
        "running",
        {"progress_file": {"exists": True, "readable": False}},
    ) == ProgressPercentResult(None, None, "progress_file_unreadable")
    assert codex_progress_percent(
        _task(),
        {},
        "running",
        {"workspace": {"path": "D:/workspaces/task-1"}, "progress_file": {"exists": False}},
    ) == ProgressPercentResult(None, None, "progress_file_missing")


def test_progress_unavailable_reason_distinguishes_missing_workspace_and_missing_percent() -> None:
    assert codex_progress_percent(_task(), {}, "running", {}) == ProgressPercentResult(
        None,
        None,
        "workspace_not_ready",
    )
    assert codex_progress_percent(_task(TaskStatus.paused_for_review), {}, "plan_ready", {}) == ProgressPercentResult(
        None,
        None,
        "progress_not_available",
    )
    assert codex_progress_percent(_task(), {"percent": ""}, "running", {}) == ProgressPercentResult(
        None,
        None,
        "progress_percent_missing",
    )
    assert codex_progress_percent(_task(), {"progress_percent": "bad"}, "running", {}) == ProgressPercentResult(
        None,
        None,
        "progress_percent_invalid",
    )
