from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from backend.app.models.task import WorkflowStage, WorkflowStageRecord, WorkflowStageStatus
from backend.app.services.task_store_stage_timing import resolve_stage_timing


class TaskStoreStageTimingTests(TestCase):
    def test_running_stage_resets_previous_finish_time(self) -> None:
        created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        previous_started_at = created_at
        previous_finished_at = created_at + timedelta(minutes=20)
        existing = WorkflowStageRecord(
            id="stage-1",
            team_id="team-1",
            task_id="task-1",
            stage=WorkflowStage.training_validation,
            status=WorkflowStageStatus.completed,
            summary="Previous run completed.",
            started_at=previous_started_at,
            finished_at=previous_finished_at,
            duration_seconds=1200,
            created_at=created_at,
            updated_at=previous_finished_at,
        )

        now = previous_finished_at + timedelta(minutes=10)

        started_at, finished_at, duration_seconds = resolve_stage_timing(
            existing,
            status=WorkflowStageStatus.running,
            now=now,
        )

        self.assertEqual(started_at, now)
        self.assertIsNone(finished_at)
        self.assertIsNone(duration_seconds)

    def test_completed_stage_without_existing_start_uses_record_creation_time(self) -> None:
        created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        existing = WorkflowStageRecord(
            id="stage-1",
            team_id="team-1",
            task_id="task-1",
            stage=WorkflowStage.report_generation,
            status=WorkflowStageStatus.pending,
            summary="Waiting for report.",
            started_at=None,
            finished_at=None,
            duration_seconds=None,
            created_at=created_at,
            updated_at=created_at,
        )

        now = created_at + timedelta(minutes=15)

        started_at, finished_at, duration_seconds = resolve_stage_timing(
            existing,
            status=WorkflowStageStatus.completed,
            now=now,
        )

        self.assertEqual(started_at, created_at)
        self.assertEqual(finished_at, now)
        self.assertEqual(duration_seconds, 900)
