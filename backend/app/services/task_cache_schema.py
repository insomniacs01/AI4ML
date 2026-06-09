from __future__ import annotations

import sqlite3


def ensure_task_cache_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_cache (
            team_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            is_detail INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (team_id, task_id)
        )
        """
    )
    _ensure_task_detail_column(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_cache_team_updated
        ON task_cache(team_id, updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stage_cache (
            team_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY (team_id, task_id, stage)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stage_cache_task_updated
        ON stage_cache(team_id, task_id, updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS human_request_cache (
            team_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY (team_id, task_id, request_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_human_request_cache_task_updated
        ON human_request_cache(team_id, task_id, updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS human_request_cache_state (
            team_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY (team_id, task_id)
        )
        """
    )


def _ensure_task_detail_column(conn: sqlite3.Connection) -> None:
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(task_cache)").fetchall()}
    if "is_detail" not in columns:
        conn.execute("ALTER TABLE task_cache ADD COLUMN is_detail INTEGER NOT NULL DEFAULT 0")
