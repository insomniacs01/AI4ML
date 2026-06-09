from __future__ import annotations

import sqlite3

from backend.app.models.task import TaskHumanRequestRecord, TaskRecord, WorkflowStageRecord
from backend.app.services.task_cache_payloads import (
    encode_human_request_payload,
    encode_stage_payload,
    encode_task_payload,
)


def mark_task_synced(conn: sqlite3.Connection, team_id: str, task_id: str, *, synced_at: str) -> None:
    conn.execute(
        """
        UPDATE task_cache
        SET synced_at = ?
        WHERE team_id = ? AND task_id = ?
        """,
        (synced_at, team_id, task_id),
    )


def write_task_cache(
    conn: sqlite3.Connection,
    task: TaskRecord,
    *,
    synced_at: str,
    is_detail: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO task_cache (
            team_id,
            task_id,
            payload,
            updated_at,
            synced_at,
            is_detail
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(team_id, task_id) DO UPDATE SET
            payload = excluded.payload,
            updated_at = excluded.updated_at,
            synced_at = excluded.synced_at,
            is_detail = CASE
                WHEN task_cache.is_detail = 1 THEN 1
                ELSE excluded.is_detail
            END
        """,
        (
            task.team_id,
            task.id,
            encode_task_payload(task),
            task.updated_at.isoformat(),
            synced_at,
            1 if is_detail else 0,
        ),
    )


def write_stage_cache(
    conn: sqlite3.Connection,
    record: WorkflowStageRecord,
    *,
    synced_at: str,
    stage: str,
) -> None:
    conn.execute(
        """
        INSERT INTO stage_cache (
            team_id,
            task_id,
            stage,
            payload,
            updated_at,
            synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(team_id, task_id, stage) DO UPDATE SET
            payload = excluded.payload,
            updated_at = excluded.updated_at,
            synced_at = excluded.synced_at
        """,
        (
            record.team_id,
            record.task_id,
            stage,
            encode_stage_payload(record),
            record.updated_at.isoformat(),
            synced_at,
        ),
    )


def replace_human_request_cache(
    conn: sqlite3.Connection,
    team_id: str,
    task_id: str,
    requests: list[TaskHumanRequestRecord],
    *,
    synced_at: str,
) -> None:
    conn.execute(
        "DELETE FROM human_request_cache WHERE team_id = ? AND task_id = ?",
        (team_id, task_id),
    )
    conn.executemany(
        """
        INSERT INTO human_request_cache (
            team_id,
            task_id,
            request_id,
            payload,
            updated_at,
            synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                request.team_id,
                request.task_id,
                request.id,
                encode_human_request_payload(request),
                request.updated_at.isoformat(),
                synced_at,
            )
            for request in requests
        ],
    )
    mark_human_requests_synced(conn, team_id, task_id, synced_at=synced_at)


def delete_task_rows(conn: sqlite3.Connection, rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    conn.executemany(
        "DELETE FROM task_cache WHERE team_id = ? AND task_id = ?",
        rows,
    )
    conn.executemany(
        "DELETE FROM stage_cache WHERE team_id = ? AND task_id = ?",
        rows,
    )
    conn.executemany(
        "DELETE FROM human_request_cache WHERE team_id = ? AND task_id = ?",
        rows,
    )
    conn.executemany(
        "DELETE FROM human_request_cache_state WHERE team_id = ? AND task_id = ?",
        rows,
    )


def mark_stage_synced(
    conn: sqlite3.Connection,
    team_id: str,
    task_id: str,
    stage: str,
    *,
    synced_at: str,
) -> None:
    conn.execute(
        """
        UPDATE stage_cache
        SET synced_at = ?
        WHERE team_id = ? AND task_id = ? AND stage = ?
        """,
        (synced_at, team_id, task_id, stage),
    )


def mark_human_requests_synced(
    conn: sqlite3.Connection,
    team_id: str,
    task_id: str,
    *,
    synced_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO human_request_cache_state (team_id, task_id, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(team_id, task_id) DO UPDATE SET
            synced_at = excluded.synced_at
        """,
        (team_id, task_id, synced_at),
    )


def delete_human_request_cache(conn: sqlite3.Connection, team_id: str, task_id: str) -> None:
    conn.execute(
        "DELETE FROM human_request_cache WHERE team_id = ? AND task_id = ?",
        (team_id, task_id),
    )
    conn.execute(
        "DELETE FROM human_request_cache_state WHERE team_id = ? AND task_id = ?",
        (team_id, task_id),
    )
