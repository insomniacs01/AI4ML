from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.models.task import RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_cache_upsert import CachedTaskState, build_task_upsert_plan


def _task(*, name: str, updated_at: datetime) -> TaskRecord:
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name=name,
        description=f"{name} description",
        status=TaskStatus.running,
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_new_task_plan_writes_with_requested_detail_flag() -> None:
    now = datetime.now(timezone.utc)
    task = _task(name="new", updated_at=now)

    plan = build_task_upsert_plan(None, task, detail=False)

    assert plan.should_write is True
    assert plan.is_detail is False
    assert plan.task is task


def test_newer_summary_merges_into_existing_detail_without_losing_detail_payload() -> None:
    older = datetime.now(timezone.utc)
    newer = older + timedelta(minutes=1)
    detail_task = _task(name="detail", updated_at=older)
    detail_task.last_run = RunSummary(
        best_model="model-a",
        metric_name="accuracy",
        metric_value=0.91,
        output_dir="D:/runs/task-1",
    )
    summary_task = _task(name="summary", updated_at=newer)
    existing = CachedTaskState(task=detail_task, updated_at=older, is_detail=True)

    plan = build_task_upsert_plan(existing, summary_task, detail=False)

    assert plan.should_write is True
    assert plan.is_detail is True
    assert plan.task.name == "summary"
    assert plan.task.description == "summary description"
    assert plan.task.last_run is not None
    assert plan.task.last_run.best_model == "model-a"


def test_older_summary_does_not_overwrite_newer_detail() -> None:
    newer = datetime.now(timezone.utc)
    older = newer - timedelta(minutes=1)
    existing = CachedTaskState(task=_task(name="detail", updated_at=newer), updated_at=newer, is_detail=True)

    plan = build_task_upsert_plan(existing, _task(name="summary", updated_at=older), detail=False)

    assert plan.should_write is False


def test_detail_payload_upgrades_existing_summary_even_with_same_timestamp() -> None:
    now = datetime.now(timezone.utc)
    existing = CachedTaskState(task=_task(name="summary", updated_at=now), updated_at=now, is_detail=False)
    detail_task = _task(name="detail", updated_at=now)

    plan = build_task_upsert_plan(existing, detail_task, detail=True)

    assert plan.should_write is True
    assert plan.is_detail is True
    assert plan.task is detail_task
