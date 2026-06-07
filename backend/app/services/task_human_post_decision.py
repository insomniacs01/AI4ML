from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_human_task_state import (
    apply_task_ready_for_human_rerun,
    apply_task_rerun_request,
    apply_task_resume_after_human,
    apply_task_waiting_for_human,
)
from backend.app.services.task_human_transitions import (
    READY_FOR_RERUN_ACTION,
    REQUEST_RERUN_AND_WAIT_ACTION,
    RESUME_TASK_ACTION,
    WAIT_FOR_HUMAN_ACTION,
    PostDecisionTaskAction,
)


def save_task_waiting_for_human(
    task_store: Any,
    task: TaskRecord,
    *,
    access_token: str,
    manual_hold: bool,
) -> TaskRecord:
    apply_task_waiting_for_human(
        task,
        manual_hold=manual_hold,
        updated_at=datetime.now(timezone.utc),
    )
    return task_store.save_task(task, access_token=access_token)


def save_task_resume_after_human(task_store: Any, task: TaskRecord, *, access_token: str) -> TaskRecord:
    apply_task_resume_after_human(task, resumed_at=datetime.now(timezone.utc))
    return task_store.save_task(task, access_token=access_token)


def apply_post_decision_task_action(
    task_store: Any,
    task: TaskRecord,
    *,
    action: PostDecisionTaskAction,
    access_token: str,
    reason: str,
    rerun_from_stage: str | None = None,
) -> TaskRecord:
    if action == WAIT_FOR_HUMAN_ACTION:
        return save_task_waiting_for_human(
            task_store,
            task,
            access_token=access_token,
            manual_hold=True,
        )
    if action == READY_FOR_RERUN_ACTION:
        apply_task_ready_for_human_rerun(
            task,
            reason=reason,
            rerun_from_stage=rerun_from_stage,
            updated_at=datetime.now(timezone.utc),
        )
        return task_store.save_task(task, access_token=access_token)
    if action == REQUEST_RERUN_AND_WAIT_ACTION:
        apply_task_rerun_request(
            task,
            reason=reason,
            rerun_from_stage=rerun_from_stage,
            requested_at=datetime.now(timezone.utc),
        )
        return save_task_waiting_for_human(
            task_store,
            task,
            access_token=access_token,
            manual_hold=True,
        )
    if action == RESUME_TASK_ACTION:
        return save_task_resume_after_human(task_store, task, access_token=access_token)
    raise RuntimeError(f"unsupported post decision task action: {action}")
