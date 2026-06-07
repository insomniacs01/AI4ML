from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_human_context import HUMAN_LOOP_KEY
from backend.app.services.task_human_post_decision import (
    apply_post_decision_task_action,
    save_task_resume_after_human,
    save_task_waiting_for_human,
)
from backend.app.services.task_human_transitions import (
    READY_FOR_RERUN_ACTION,
    REQUEST_RERUN_AND_WAIT_ACTION,
)


class _FakeTaskStore:
    def __init__(self) -> None:
        self.saved_tasks: list[TaskRecord] = []
        self.access_tokens: list[str] = []

    def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        self.saved_tasks.append(task.model_copy(deep=True))
        self.access_tokens.append(access_token)
        return task


def _task(
    *,
    status: TaskStatus = TaskStatus.planning,
    dataset_filename: str | None = None,
    structured_requirements: dict | None = None,
) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-human-post-decision",
        team_id="team-1",
        created_by="user-1",
        name="Human post decision",
        description="Task for post-decision state tests.",
        status=status,
        dataset_filename=dataset_filename,
        structured_requirements=structured_requirements,
        created_at=now,
        updated_at=now,
    )


def test_save_task_waiting_for_human_pauses_and_persists_token() -> None:
    store = _FakeTaskStore()
    task = _task(status=TaskStatus.planning)

    saved = save_task_waiting_for_human(
        store,
        task,
        access_token="token",
        manual_hold=True,
    )

    human_loop = saved.structured_requirements[HUMAN_LOOP_KEY]
    assert saved.status == TaskStatus.paused_for_review
    assert human_loop["previous_status"] == "planning"
    assert human_loop["manual_hold"] is True
    assert "updated_at" in human_loop
    assert store.saved_tasks == [saved]
    assert store.access_tokens == ["token"]


def test_post_decision_rerun_and_wait_marks_rerun_then_pauses() -> None:
    store = _FakeTaskStore()
    task = _task(status=TaskStatus.planning)

    saved = apply_post_decision_task_action(
        store,
        task,
        action=REQUEST_RERUN_AND_WAIT_ACTION,
        access_token="token",
        reason="Use F1.",
        rerun_from_stage="training_validation",
    )

    human_loop = saved.structured_requirements[HUMAN_LOOP_KEY]
    assert saved.status == TaskStatus.paused_for_review
    assert human_loop["previous_status"] == "planning"
    assert human_loop["rerun_requested"] is True
    assert human_loop["rerun_reason"] == "Use F1."
    assert human_loop["rerun_from_stage"] == "training_validation"
    assert human_loop["manual_hold"] is True
    assert len(store.saved_tasks) == 1
    assert store.access_tokens == ["token"]


def test_post_decision_ready_for_rerun_saves_uploaded_task_when_dataset_exists() -> None:
    store = _FakeTaskStore()
    task = _task(status=TaskStatus.paused_for_review, dataset_filename="data.csv")

    saved = apply_post_decision_task_action(
        store,
        task,
        action=READY_FOR_RERUN_ACTION,
        access_token="token",
        reason="Use F1.",
        rerun_from_stage="training_validation",
    )

    human_loop = saved.structured_requirements[HUMAN_LOOP_KEY]
    assert saved.status == TaskStatus.uploaded
    assert saved.notes == "人工协同要求重新运行：Use F1."
    assert human_loop["rerun_requested"] is True
    assert human_loop["manual_hold"] is False
    assert store.saved_tasks == [saved]


def test_save_task_resume_after_human_restores_previous_status() -> None:
    store = _FakeTaskStore()
    task = _task(
        status=TaskStatus.paused_for_review,
        structured_requirements={HUMAN_LOOP_KEY: {"previous_status": "planning", "manual_hold": True}},
    )

    saved = save_task_resume_after_human(store, task, access_token="token")

    human_loop = saved.structured_requirements[HUMAN_LOOP_KEY]
    assert saved.status == TaskStatus.planning
    assert human_loop["manual_hold"] is False
    assert "resumed_at" in human_loop
    assert store.saved_tasks == [saved]
    assert store.access_tokens == ["token"]
