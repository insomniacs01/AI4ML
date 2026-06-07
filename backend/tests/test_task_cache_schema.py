from __future__ import annotations

import sqlite3

from backend.app.services.task_cache_schema import ensure_task_cache_schema


def test_schema_adds_detail_column_to_existing_task_cache_table() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE task_cache (
            team_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY (team_id, task_id)
        )
        """
    )

    ensure_task_cache_schema(conn)

    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(task_cache)").fetchall()}
    assert "is_detail" in columns


def test_schema_creates_stage_cache_and_expected_indexes() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    ensure_task_cache_schema(conn)

    tables = {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    indexes = {
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    }
    assert {"task_cache", "stage_cache"}.issubset(tables)
    assert {"idx_task_cache_team_updated", "idx_stage_cache_task_updated"}.issubset(indexes)
