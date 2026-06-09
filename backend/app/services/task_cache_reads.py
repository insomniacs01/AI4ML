from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from backend.app.models.task import TaskHumanRequestRecord, TaskRecord, WorkflowStageRecord
from backend.app.services.task_cache_payloads import (
    decode_human_request_payload,
    decode_stage_payload,
    decode_task_payload,
)
from backend.app.services.task_cache_stage_upsert import CachedStageState, stage_key
from backend.app.services.task_cache_upsert import CachedTaskState
from backend.app.services.task_human_request_status import ACTIVE_HUMAN_REQUEST_STATUSES


def list_cached_tasks(conn: sqlite3.Connection, team_id: str) -> list[TaskRecord]:
    rows = conn.execute(
        """
        SELECT payload
        FROM task_cache
        WHERE team_id = ?
        ORDER BY updated_at DESC
        """,
        (team_id,),
    ).fetchall()
    tasks: list[TaskRecord] = []
    for row in rows:
        task = decode_task_payload(row["payload"])
        if task is not None:
            tasks.append(task)
    return tasks


def get_cached_task(
    conn: sqlite3.Connection,
    team_id: str,
    task_id: str,
    *,
    require_detail: bool = False,
) -> TaskRecord | None:
    detail_clause = " AND is_detail = 1" if require_detail else ""
    row = conn.execute(
        f"""
        SELECT payload
        FROM task_cache
        WHERE team_id = ? AND task_id = ?
        {detail_clause}
        LIMIT 1
        """,
        (team_id, task_id),
    ).fetchone()
    if row is None:
        return None
    return decode_task_payload(row["payload"])


def stale_team_task_ids(conn: sqlite3.Connection, team_id: str, live_task_ids: set[str]) -> list[str]:
    rows = conn.execute(
        "SELECT task_id FROM task_cache WHERE team_id = ?",
        (team_id,),
    ).fetchall()
    return [str(row["task_id"]) for row in rows if str(row["task_id"]) not in live_task_ids]


def list_cached_stage_records(conn: sqlite3.Connection, team_id: str, task_id: str) -> list[WorkflowStageRecord]:
    rows = conn.execute(
        """
        SELECT payload
        FROM stage_cache
        WHERE team_id = ? AND task_id = ?
        ORDER BY updated_at DESC
        """,
        (team_id, task_id),
    ).fetchall()
    records: list[WorkflowStageRecord] = []
    for row in rows:
        record = decode_stage_payload(row["payload"])
        if record is not None:
            records.append(record)
    return records


def list_cached_human_requests(
    conn: sqlite3.Connection,
    team_id: str,
    task_id: str,
) -> list[TaskHumanRequestRecord]:
    rows = conn.execute(
        """
        SELECT payload
        FROM human_request_cache
        WHERE team_id = ? AND task_id = ?
        ORDER BY updated_at DESC
        """,
        (team_id, task_id),
    ).fetchall()
    requests: list[TaskHumanRequestRecord] = []
    for row in rows:
        request = decode_human_request_payload(row["payload"])
        if request is not None:
            requests.append(request)
    return sorted(
        requests,
        key=lambda item: (
            0 if item.status in ACTIVE_HUMAN_REQUEST_STATUSES else 1,
            -item.updated_at.timestamp(),
        ),
    )


def latest_task_sync(
    conn: sqlite3.Connection,
    *,
    team_id: str,
    task_id: str | None = None,
    require_detail: bool = False,
) -> datetime | None:
    if task_id:
        detail_clause = " AND is_detail = 1" if require_detail else ""
        query = f"SELECT synced_at FROM task_cache WHERE team_id = ? AND task_id = ?{detail_clause} LIMIT 1"
        params: tuple[str, ...] = (team_id, task_id)
    else:
        query = "SELECT MAX(synced_at) AS synced_at FROM task_cache WHERE team_id = ?"
        params = (team_id,)
    row = conn.execute(query, params).fetchone()
    if row is None or not row["synced_at"]:
        return None
    return parse_cache_datetime(str(row["synced_at"]))


def latest_stage_sync(conn: sqlite3.Connection, team_id: str, task_id: str) -> datetime | None:
    row = conn.execute(
        """
        SELECT MAX(synced_at) AS synced_at
        FROM stage_cache
        WHERE team_id = ? AND task_id = ?
        """,
        (team_id, task_id),
    ).fetchone()
    if row is None or not row["synced_at"]:
        return None
    return parse_cache_datetime(str(row["synced_at"]))


def latest_human_request_sync(conn: sqlite3.Connection, team_id: str, task_id: str) -> datetime | None:
    row = conn.execute(
        """
        SELECT synced_at
        FROM human_request_cache_state
        WHERE team_id = ? AND task_id = ?
        LIMIT 1
        """,
        (team_id, task_id),
    ).fetchone()
    if row is None or not row["synced_at"]:
        return None
    return parse_cache_datetime(str(row["synced_at"]))


def cached_task_state(conn: sqlite3.Connection, task: TaskRecord) -> CachedTaskState | None:
    row = conn.execute(
        """
        SELECT payload, updated_at, is_detail
        FROM task_cache
        WHERE team_id = ? AND task_id = ?
        LIMIT 1
        """,
        (task.team_id, task.id),
    ).fetchone()
    if row is None:
        return None
    return CachedTaskState(
        task=decode_task_payload(str(row["payload"])),
        updated_at=parse_cache_datetime(str(row["updated_at"])),
        is_detail=int(row["is_detail"] or 0) == 1,
    )


def cached_stage_state(conn: sqlite3.Connection, record: WorkflowStageRecord) -> CachedStageState | None:
    row = conn.execute(
        """
        SELECT updated_at
        FROM stage_cache
        WHERE team_id = ? AND task_id = ? AND stage = ?
        LIMIT 1
        """,
        (record.team_id, record.task_id, stage_key(record.stage)),
    ).fetchone()
    if row is None:
        return None
    return CachedStageState(updated_at=parse_cache_datetime(str(row["updated_at"])))


def parse_cache_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def cache_entry_is_fresh(
    synced_at: datetime | None,
    *,
    ttl_seconds: int,
    now: datetime | None = None,
) -> bool:
    if synced_at is None:
        return False
    reference_time = now or datetime.now(timezone.utc)
    return reference_time - synced_at <= timedelta(seconds=ttl_seconds)
