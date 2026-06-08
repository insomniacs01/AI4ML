from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus
from backend.app.services.token_usage_summary import (
    build_task_token_usage_item,
    build_team_token_usage_response,
    get_task_analysis_token_usage,
    make_token_usage_report,
    sum_token_usage_reports,
)


def _task(task_id: str, *, updated_at: datetime | None = None) -> TaskRecord:
    now = updated_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id=task_id,
        team_id="team-1",
        created_by="user-1",
        name=f"Task {task_id}",
        description="Token usage task.",
        status=TaskStatus.completed,
        created_at=now,
        updated_at=now,
    )


def test_get_task_analysis_token_usage_reads_structured_requirements_payload() -> None:
    task = _task("analysis")
    task.structured_requirements = {
        "token_usage": {
            "input_tokens": "3",
            "output_tokens": 4,
            "sessions": [{"session_name": "analysis", "input_tokens": 3, "output_tokens": 4, "total_tokens": 7}],
        }
    }

    usage = get_task_analysis_token_usage(task)

    assert usage is not None
    assert usage.input_tokens == 3
    assert usage.output_tokens == 4
    assert usage.total_tokens == 7
    assert usage.sessions[0]["session_name"] == "analysis"


def test_sum_token_usage_reports_merges_session_totals() -> None:
    usage = sum_token_usage_reports(
        [
            make_token_usage_report(
                input_tokens=1,
                output_tokens=2,
                sessions=[{"session_name": "a", "input_tokens": 1, "output_tokens": 2, "total_tokens": 3}],
            ),
            make_token_usage_report(
                input_tokens=3,
                output_tokens=4,
                sessions=[{"session_name": "a", "input_tokens": 3, "output_tokens": 4, "total_tokens": 7}],
            ),
        ]
    )

    assert usage.input_tokens == 4
    assert usage.output_tokens == 6
    assert usage.total_tokens == 10
    assert usage.sessions == [{"session_name": "a", "input_tokens": 4, "output_tokens": 6, "total_tokens": 10}]


def test_build_task_token_usage_item_prefers_latest_attempt_usage_for_run_usage() -> None:
    task = _task("run")
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir="run-output",
        token_usage=make_token_usage_report(input_tokens=1, output_tokens=1),
    )
    task.last_run_attempt = RunAttempt(
        output_dir="attempt-output",
        token_usage=make_token_usage_report(input_tokens=5, output_tokens=6),
    )

    item = build_task_token_usage_item(task)

    assert item.run_token_usage is not None
    assert item.run_token_usage.total_tokens == 11
    assert item.combined_token_usage.total_tokens == 11


def test_build_team_token_usage_response_sorts_items_and_totals() -> None:
    older = _task("older", updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    older.analysis_token_usage = make_token_usage_report(input_tokens=1, output_tokens=2)
    newer = _task("newer", updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    newer.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir="run-output",
        token_usage=make_token_usage_report(input_tokens=3, output_tokens=4),
    )

    response = build_team_token_usage_response("team-1", [older, newer])

    assert [item.task_id for item in response.items] == ["newer", "older"]
    assert response.task_count == 2
    assert response.tasks_with_analysis_usage == 1
    assert response.tasks_with_run_usage == 1
    assert response.combined_totals.total_tokens == 10
