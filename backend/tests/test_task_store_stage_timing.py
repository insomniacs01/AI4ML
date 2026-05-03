from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from backend.app.models.task import WorkflowStage, WorkflowStageRecord, WorkflowStageStatus
from backend.app.services.task_store import TaskStore


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

        started_at, finished_at, duration_seconds = TaskStore._resolve_stage_timing(
            existing,
            status=WorkflowStageStatus.running,
        )

        self.assertIsNotNone(started_at)
        self.assertGreater(started_at, previous_finished_at)
        self.assertIsNone(finished_at)
        self.assertIsNone(duration_seconds)

