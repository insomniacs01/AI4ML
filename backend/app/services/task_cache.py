from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from backend.app.models.task import TaskRecord, WorkflowStageRecord
from backend.app.services.task_cache_payloads import (
    decode_stage_payload,
    decode_task_payload,
)
from backend.app.services.task_cache_schema import ensure_task_cache_schema
from backend.app.services.task_cache_stage_upsert import (
    CachedStageState,
    StageUpsertPlan,
    build_stage_upsert_plan,
    stage_key,
)
from backend.app.services.task_cache_upsert import CachedTaskState, TaskUpsertPlan, build_task_upsert_plan
from backend.app.services.task_cache_writes import (
    delete_task_rows,
    mark_stage_synced,
    mark_task_synced,
    write_stage_cache,
    write_task_cache,
)


class TaskCache:
    def __init__(self, path: Path, *, ttl_seconds: int = 30) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def list_tasks(self, team_id: str) -> list[TaskRecord]:
        with self._connect() as conn:
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

    def get_task(self, team_id: str, task_id: str, *, require_detail: bool = False) -> TaskRecord | None:
        detail_clause = " AND is_detail = 1" if require_detail else ""
        with self._connect() as conn:
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

    def upsert_tasks(self, tasks: list[TaskRecord], *, detail: bool = False) -> int:
        if not tasks:
            return 0
        synced_at = self._now_iso()
        with self._lock, self._connect() as conn:
            changed = 0
            for task in tasks:
                plan = self._task_upsert_plan(conn, task, detail=detail)
                if not plan.should_write:
                    mark_task_synced(conn, task.team_id, task.id, synced_at=synced_at)
                    continue
                write_task_cache(conn, plan.task, synced_at=synced_at, is_detail=plan.is_detail)
                changed += 1
        return changed

    def upsert_task(self, task: TaskRecord, *, detail: bool = True) -> bool:
        return self.upsert_tasks([task], detail=detail) > 0

    def delete_task(self, team_id: str, task_id: str) -> None:
        with self._lock, self._connect() as conn:
            delete_task_rows(conn, [(team_id, task_id)])

    def prune_team_tasks(self, team_id: str, live_task_ids: set[str]) -> int:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT task_id FROM task_cache WHERE team_id = ?",
                (team_id,),
            ).fetchall()
            stale_ids = [str(row["task_id"]) for row in rows if str(row["task_id"]) not in live_task_ids]
            if not stale_ids:
                return 0
            delete_task_rows(conn, [(team_id, task_id) for task_id in stale_ids])
            return len(stale_ids)

    def list_stage_records(self, team_id: str, task_id: str) -> list[WorkflowStageRecord]:
        with self._connect() as conn:
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

    def upsert_stage_records(self, records: list[WorkflowStageRecord]) -> int:
        if not records:
            return 0
        synced_at = self._now_iso()
        with self._lock, self._connect() as conn:
            changed = 0
            for record in records:
                plan = self._stage_upsert_plan(conn, record)
                if not plan.should_write:
                    mark_stage_synced(conn, record.team_id, record.task_id, plan.stage, synced_at=synced_at)
                    continue
                write_stage_cache(conn, record, synced_at=synced_at, stage=plan.stage)
                changed += 1
        return changed

    def has_fresh_team_cache(self, team_id: str) -> bool:
        synced_at = self._latest_sync(team_id=team_id)
        return self._is_fresh(synced_at)

    def has_fresh_task_cache(self, team_id: str, task_id: str, *, require_detail: bool = False) -> bool:
        synced_at = self._latest_sync(team_id=team_id, task_id=task_id, require_detail=require_detail)
        return self._is_fresh(synced_at)

    def has_fresh_stage_cache(self, team_id: str, task_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(synced_at) AS synced_at
                FROM stage_cache
                WHERE team_id = ? AND task_id = ?
                """,
                (team_id, task_id),
            ).fetchone()
        if row is None or not row["synced_at"]:
            return False
        return self._is_fresh(self._parse_datetime(str(row["synced_at"])))

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            ensure_task_cache_schema(conn)

    def _latest_sync(
        self,
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
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if row is None or not row["synced_at"]:
            return None
        return self._parse_datetime(str(row["synced_at"]))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _task_upsert_plan(
        self,
        conn: sqlite3.Connection,
        task: TaskRecord,
        *,
        detail: bool,
    ) -> TaskUpsertPlan:
        return build_task_upsert_plan(self._cached_task_state(conn, task), task, detail=detail)

    def _cached_task_state(self, conn: sqlite3.Connection, task: TaskRecord) -> CachedTaskState | None:
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
            updated_at=self._parse_datetime(str(row["updated_at"])),
            is_detail=int(row["is_detail"] or 0) == 1,
        )

    def _stage_upsert_plan(self, conn: sqlite3.Connection, record: WorkflowStageRecord) -> StageUpsertPlan:
        existing = self._cached_stage_state(conn, record)
        return build_stage_upsert_plan(existing, record.stage, record.updated_at)

    def _cached_stage_state(self, conn: sqlite3.Connection, record: WorkflowStageRecord) -> CachedStageState | None:
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
        return CachedStageState(updated_at=self._parse_datetime(str(row["updated_at"])))

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _is_fresh(self, synced_at: datetime | None) -> bool:
        if synced_at is None:
            return False
        return datetime.now(timezone.utc) - synced_at <= timedelta(seconds=self.ttl_seconds)
