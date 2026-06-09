from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from backend.app.models.task import TaskHumanRequestRecord, TaskRecord, WorkflowStageRecord
from backend.app.services.task_cache_reads import (
    cache_entry_is_fresh,
    cached_stage_state,
    cached_task_state,
    get_cached_task,
    latest_human_request_sync,
    latest_stage_sync,
    latest_task_sync,
    list_cached_human_requests,
    list_cached_stage_records,
    list_cached_tasks,
    stale_team_task_ids,
)
from backend.app.services.task_cache_schema import ensure_task_cache_schema
from backend.app.services.task_cache_stage_upsert import (
    StageUpsertPlan,
    build_stage_upsert_plan,
)
from backend.app.services.task_cache_upsert import TaskUpsertPlan, build_task_upsert_plan
from backend.app.services.task_cache_writes import (
    delete_human_request_cache,
    delete_task_rows,
    mark_stage_synced,
    mark_task_synced,
    replace_human_request_cache,
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
            return list_cached_tasks(conn, team_id)

    def get_task(self, team_id: str, task_id: str, *, require_detail: bool = False) -> TaskRecord | None:
        with self._connect() as conn:
            return get_cached_task(conn, team_id, task_id, require_detail=require_detail)

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
            stale_ids = stale_team_task_ids(conn, team_id, live_task_ids)
            if not stale_ids:
                return 0
            delete_task_rows(conn, [(team_id, task_id) for task_id in stale_ids])
            return len(stale_ids)

    def list_stage_records(self, team_id: str, task_id: str) -> list[WorkflowStageRecord]:
        with self._connect() as conn:
            return list_cached_stage_records(conn, team_id, task_id)

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

    def list_human_requests(self, team_id: str, task_id: str) -> list[TaskHumanRequestRecord]:
        with self._connect() as conn:
            return list_cached_human_requests(conn, team_id, task_id)

    def replace_human_requests(
        self,
        team_id: str,
        task_id: str,
        requests: list[TaskHumanRequestRecord],
    ) -> None:
        synced_at = self._now_iso()
        with self._lock, self._connect() as conn:
            replace_human_request_cache(conn, team_id, task_id, requests, synced_at=synced_at)

    def invalidate_human_requests(self, team_id: str, task_id: str) -> None:
        with self._lock, self._connect() as conn:
            delete_human_request_cache(conn, team_id, task_id)

    def has_fresh_team_cache(self, team_id: str) -> bool:
        synced_at = self._latest_sync(team_id=team_id)
        return self._is_fresh(synced_at)

    def has_fresh_task_cache(self, team_id: str, task_id: str, *, require_detail: bool = False) -> bool:
        synced_at = self._latest_sync(team_id=team_id, task_id=task_id, require_detail=require_detail)
        return self._is_fresh(synced_at)

    def has_fresh_stage_cache(self, team_id: str, task_id: str) -> bool:
        with self._connect() as conn:
            synced_at = latest_stage_sync(conn, team_id, task_id)
        return cache_entry_is_fresh(synced_at, ttl_seconds=self.ttl_seconds)

    def has_human_request_cache(self, team_id: str, task_id: str) -> bool:
        with self._connect() as conn:
            return latest_human_request_sync(conn, team_id, task_id) is not None

    def has_fresh_human_request_cache(self, team_id: str, task_id: str) -> bool:
        with self._connect() as conn:
            synced_at = latest_human_request_sync(conn, team_id, task_id)
        return cache_entry_is_fresh(synced_at, ttl_seconds=self.ttl_seconds)

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
        with self._connect() as conn:
            return latest_task_sync(conn, team_id=team_id, task_id=task_id, require_detail=require_detail)

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
        return build_task_upsert_plan(cached_task_state(conn, task), task, detail=detail)

    def _stage_upsert_plan(self, conn: sqlite3.Connection, record: WorkflowStageRecord) -> StageUpsertPlan:
        existing = cached_stage_state(conn, record)
        return build_stage_upsert_plan(existing, record.stage, record.updated_at)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _is_fresh(self, synced_at: datetime | None) -> bool:
        return cache_entry_is_fresh(synced_at, ttl_seconds=self.ttl_seconds)
