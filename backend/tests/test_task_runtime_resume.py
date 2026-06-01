from __future__ import annotations

from datetime import datetime, timezone

from backend.app.api.routes.task_runtime import _codex_interrupted, _codex_waiting_plan_approval
from backend.app.models.task import TaskRecord, TaskStatus


def _task(*, codex_status: str | None) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-resume",
        team_id="team-1",
        created_by="user-1",
        name="Resume Task",
        description="Resume Codex task.",
        status=TaskStatus.paused_for_review,
        codex_status=codex_status,
        created_at=now,
        updated_at=now,
    )


def test_waiting_plan_approval_is_not_interrupted_resume() -> None:
    progress = {
        "status": "waiting_plan_approval",
        "current_step": "awaiting_plan_approval",
    }

    assert _codex_waiting_plan_approval(_task(codex_status="waiting_plan_approval"), progress) is True
    assert _codex_interrupted(_task(codex_status="waiting_plan_approval"), progress) is False


def test_interrupted_status_is_interrupted_resume() -> None:
    progress = {"status": "interrupted"}

    assert _codex_interrupted(_task(codex_status="interrupted"), progress) is True
    assert _codex_waiting_plan_approval(_task(codex_status="interrupted"), progress) is False
