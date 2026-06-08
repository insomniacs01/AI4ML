from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from backend.app.models.task import TaskRecord, TaskStatus, WorkflowStage, WorkflowStageRecord, WorkflowStageStatus
from backend.app.services.task_cache_reads import (
    cache_entry_is_fresh,
    cached_stage_state,
    cached_task_state,
    get_cached_task,
    latest_stage_sync,
    latest_task_sync,
    list_cached_stage_records,
    list_cached_tasks,
    parse_cache_datetime,
    stale_team_task_ids,
)
from backend.app.services.task_cache_schema import ensure_task_cache_schema
from backend.app.services.task_cache_writes import write_stage_cache, write_task_cache


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_task_cache_schema(conn)
    return conn


def _task(task_id: str = "task-1", *, updated_at: datetime | None = None) -> TaskRecord:
    now = updated_at or datetime.now(timezone.utc)
    return TaskRecord(
        id=task_id,
        team_id="team-1",
        created_by="user-1",
        name=f"Task {task_id}",
        description="Cached task",
        status=TaskStatus.running,
        created_at=now,
        updated_at=now,
    )


def _stage(updated_at: datetime | None = None) -> WorkflowStageRecord:
    now = updated_at or datetime.now(timezone.utc)
    return WorkflowStageRecord(
        id="stage-1",
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.training_validation,
        status=WorkflowStageStatus.running,
        created_at=now,
        updated_at=now,
    )


def test_task_cache_read_helpers_decode_tasks_and_detail_rows() -> None:
    conn = _connect()
    now = datetime.now(timezone.utc)
    task = _task(updated_at=now)

    write_task_cache(conn, task, synced_at=now.isoformat(), is_detail=True)
    conn.execute(
        """
        INSERT INTO task_cache (team_id, task_id, updated_at, synced_at, is_detail, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("team-1", "bad-task", now.isoformat(), now.isoformat(), 0, "{invalid"),
    )

    assert [item.id for item in list_cached_tasks(conn, "team-1")] == ["task-1"]
    assert get_cached_task(conn, "team-1", "task-1", require_detail=True).id == "task-1"
    assert get_cached_task(conn, "team-1", "bad-task") is None
    assert latest_task_sync(conn, team_id="team-1", task_id="task-1", require_detail=True) == now
    assert cached_task_state(conn, task).is_detail is True


def test_stage_cache_read_helpers_decode_stages_and_latest_sync() -> None:
    conn = _connect()
    now = datetime.now(timezone.utc)
    stage = _stage(updated_at=now)

    write_stage_cache(conn, stage, synced_at=now.isoformat(), stage=WorkflowStage.training_validation.value)

    records = list_cached_stage_records(conn, "team-1", "task-1")

    assert len(records) == 1
    assert records[0].stage == WorkflowStage.training_validation
    assert latest_stage_sync(conn, "team-1", "task-1") == now
    assert cached_stage_state(conn, stage).updated_at == now


def test_stale_task_ids_and_freshness_helpers() -> None:
    conn = _connect()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    write_task_cache(conn, _task("task-1", updated_at=now), synced_at=now.isoformat(), is_detail=False)
    write_task_cache(conn, _task("task-2", updated_at=now), synced_at=now.isoformat(), is_detail=False)

    assert stale_team_task_ids(conn, "team-1", {"task-2"}) == ["task-1"]
    assert parse_cache_datetime("2026-01-01T00:00:00Z") == now
    assert parse_cache_datetime("not-a-date") is None
    assert cache_entry_is_fresh(now, ttl_seconds=60, now=now + timedelta(seconds=60)) is True
    assert cache_entry_is_fresh(now, ttl_seconds=60, now=now + timedelta(seconds=61)) is False
