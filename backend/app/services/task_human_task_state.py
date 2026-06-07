from __future__ import annotations

from datetime import datetime

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_human_context import ensure_task_human_loop
from backend.app.services.task_human_stage_blueprints import get_previous_status


def apply_task_waiting_for_human(
    task: TaskRecord,
    *,
    manual_hold: bool,
    updated_at: datetime,
) -> TaskRecord:
    human_loop = ensure_task_human_loop(task)
    if task.status not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        human_loop["previous_status"] = task.status.value
    human_loop["manual_hold"] = manual_hold
    human_loop["updated_at"] = updated_at.isoformat()
    task.status = TaskStatus.paused_for_review
    return task


def apply_task_rerun_request(
    task: TaskRecord,
    *,
    reason: str,
    rerun_from_stage: str | None,
    requested_at: datetime,
) -> TaskRecord:
    human_loop = ensure_task_human_loop(task)
    human_loop["rerun_requested"] = True
    human_loop["rerun_reason"] = reason
    if rerun_from_stage:
        human_loop["rerun_from_stage"] = rerun_from_stage
    human_loop["rerun_requested_at"] = requested_at.isoformat()
    human_loop["manual_hold"] = False
    human_loop["updated_at"] = requested_at.isoformat()
    return task


def apply_task_ready_for_human_rerun(
    task: TaskRecord,
    *,
    reason: str,
    rerun_from_stage: str | None,
    updated_at: datetime,
) -> TaskRecord:
    apply_task_rerun_request(
        task,
        reason=reason,
        rerun_from_stage=rerun_from_stage,
        requested_at=updated_at,
    )
    task.status = TaskStatus.uploaded if task.dataset_filename else TaskStatus.draft
    task.notes = f"人工协同要求重新运行：{reason}"
    return task


def apply_task_resume_after_human(task: TaskRecord, *, resumed_at: datetime) -> TaskRecord:
    human_loop = ensure_task_human_loop(task)
    human_loop["manual_hold"] = False
    human_loop["resumed_at"] = resumed_at.isoformat()
    task.status = get_previous_status(task)
    return task
