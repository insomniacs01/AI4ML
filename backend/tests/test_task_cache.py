from __future__ import annotations

from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase

from backend.app.models.task import RunSummary, TaskRecord, TaskStatus, WorkflowStage, WorkflowStageRecord, WorkflowStageStatus
from backend.app.services.task_cache import TaskCache


def _task(task_id: str = "task-1", *, updated_at: datetime | None = None, name: str = "Cached Task") -> TaskRecord:
    now = updated_at or datetime.now(timezone.utc)
    return TaskRecord(
        id=task_id,
        team_id="team-1",
        created_by="user-1",
        name=name,
        description="Cached description",
        status=TaskStatus.running,
        created_at=now,
        updated_at=now,
    )


def _stage(
    stage: WorkflowStage = WorkflowStage.training_validation,
    *,
    status: WorkflowStageStatus = WorkflowStageStatus.running,
    updated_at: datetime | None = None,
    summary: str = "cached stage",
) -> WorkflowStageRecord:
    now = updated_at or datetime.now(timezone.utc)
    return WorkflowStageRecord(
        id=f"stage-{stage.value}",
        team_id="team-1",
        task_id="task-1",
        stage=stage,
        status=status,
        summary=summary,
        created_at=now,
        updated_at=now,
    )


class TaskCacheTests(TestCase):
    def test_upsert_get_list_and_delete_task(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            task = _task()

            cache.upsert_task(task)

            cached = cache.get_task("team-1", "task-1")
            self.assertIsNotNone(cached)
            self.assertEqual(cached.id, "task-1")
            self.assertEqual(cached.status, TaskStatus.running)
            self.assertTrue(cache.has_fresh_task_cache("team-1", "task-1"))
            self.assertEqual([item.id for item in cache.list_tasks("team-1")], ["task-1"])

            cache.delete_task("team-1", "task-1")

            self.assertIsNone(cache.get_task("team-1", "task-1"))

    def test_zero_ttl_marks_cache_stale(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=0)
            cache.upsert_task(_task())

            self.assertFalse(cache.has_fresh_team_cache("team-1"))

    def test_summary_cache_is_not_returned_when_detail_is_required(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            cache.upsert_tasks([_task()], detail=False)

            self.assertIsNotNone(cache.get_task("team-1", "task-1"))
            self.assertIsNone(cache.get_task("team-1", "task-1", require_detail=True))
            self.assertFalse(cache.has_fresh_task_cache("team-1", "task-1", require_detail=True))

    def test_summary_refresh_does_not_overwrite_detail_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            now = datetime.now(timezone.utc)
            detail_task = _task(updated_at=now, name="detail")
            detail_task.last_run = RunSummary(
                best_model="model-a",
                metric_name="accuracy",
                metric_value=0.91,
                output_dir="D:/runs/task-1",
            )
            summary_task = _task(updated_at=now + timedelta(minutes=1), name="summary")

            cache.upsert_task(detail_task, detail=True)
            cache.upsert_tasks([summary_task], detail=False)

            cached = cache.get_task("team-1", "task-1", require_detail=True)
            self.assertIsNotNone(cached)
            self.assertEqual(cached.name, "summary")
            self.assertIsNotNone(cached.last_run)

    def test_stage_cache_round_trip_and_delete_task(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            cache.upsert_task(_task())
            cache.upsert_stage_records([_stage()])

            records = cache.list_stage_records("team-1", "task-1")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].stage, WorkflowStage.training_validation)
            self.assertTrue(cache.has_fresh_stage_cache("team-1", "task-1"))

            cache.delete_task("team-1", "task-1")

            self.assertEqual(cache.list_stage_records("team-1", "task-1"), [])

    def test_older_stage_payload_does_not_overwrite_newer_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            newer = datetime.now(timezone.utc)
            older = newer - timedelta(minutes=5)

            self.assertEqual(cache.upsert_stage_records([_stage(updated_at=newer, summary="newer")]), 1)
            self.assertEqual(cache.upsert_stage_records([_stage(updated_at=older, summary="older")]), 0)

            records = cache.list_stage_records("team-1", "task-1")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].summary, "newer")

    def test_older_payload_does_not_overwrite_newer_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            newer = datetime.now(timezone.utc)
            older = newer - timedelta(minutes=5)

            self.assertEqual(cache.upsert_task(_task(updated_at=newer, name="newer")), True)
            self.assertEqual(cache.upsert_task(_task(updated_at=older, name="older")), False)

            cached = cache.get_task("team-1", "task-1")
            self.assertIsNotNone(cached)
            self.assertEqual(cached.name, "newer")

    def test_newer_payload_overwrites_older_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            older = datetime.now(timezone.utc)
            newer = older + timedelta(minutes=5)

            cache.upsert_task(_task(updated_at=older, name="older"))
            self.assertTrue(cache.upsert_task(_task(updated_at=newer, name="newer")))

            cached = cache.get_task("team-1", "task-1")
            self.assertIsNotNone(cached)
            self.assertEqual(cached.name, "newer")

    def test_prune_team_tasks_removes_items_missing_from_cloud_list(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60)
            cache.upsert_tasks([_task("task-1"), _task("task-2")])

            self.assertEqual(cache.prune_team_tasks("team-1", {"task-2"}), 1)

            self.assertIsNone(cache.get_task("team-1", "task-1"))
            self.assertIsNotNone(cache.get_task("team-1", "task-2"))
