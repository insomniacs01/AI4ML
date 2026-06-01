from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import get_settings
from backend.app.models.governance import TeamQuotaRecord
from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_backend import CodexBackendError, interrupt_codex_task


QUOTA_GUARDED_TASK_STATUSES = {
    TaskStatus.uploaded,
    TaskStatus.planning,
    TaskStatus.running,
    TaskStatus.paused_for_review,
    TaskStatus.waiting_human,
}
INTERRUPTABLE_TASK_STATUSES = {
    TaskStatus.uploaded,
    TaskStatus.planning,
    TaskStatus.running,
}


def quota_is_exhausted(quota: TeamQuotaRecord | None) -> bool:
    if quota is None:
        return False
    if quota.status in {"exhausted", "frozen"}:
        return True
    return quota.token_quota > 0 and quota.token_remaining <= 0


def quota_token_budget(quota: TeamQuotaRecord | None) -> int | None:
    if quota is None or quota.token_quota <= 0:
        return None
    return max(0, quota.token_remaining)


def pause_codex_task_for_quota(task_store: Any, task: TaskRecord, team_access: Any) -> TaskRecord:
    if task.status not in QUOTA_GUARDED_TASK_STATUSES:
        return task
    if task.status in INTERRUPTABLE_TASK_STATUSES:
        try:
            interrupt_codex_task(task, get_settings())
        except CodexBackendError:
            pass
    task.status = TaskStatus.paused_for_review
    task.codex_status = "interrupted"
    task.notes = "当前成员 Token 额度已用完，系统已自动暂停任务并停止继续调用大模型。请提高额度后再继续运行。"
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    quota_guard = structured.get("quota_guard") if isinstance(structured.get("quota_guard"), dict) else {}
    quota_guard.update({
        "status": "exhausted",
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "reason": "member_token_quota_exhausted",
    })
    structured["quota_guard"] = quota_guard
    task.structured_requirements = structured
    return task_store.save_task(task, access_token=team_access.access_token)


def pause_member_tasks_for_quota(task_store: Any, team_access: Any, *, user_id: str) -> list[TaskRecord]:
    tasks = task_store.list_tasks(
        team_access.team_id,
        access_token=team_access.access_token,
        lightweight=False,
        limit=200,
        prefer_cache=False,
    )
    paused_tasks: list[TaskRecord] = []
    for task in tasks:
        if task.executor_type != "codex":
            continue
        if _task_creator(task) != user_id:
            continue
        if task.status not in QUOTA_GUARDED_TASK_STATUSES:
            continue
        paused_tasks.append(pause_codex_task_for_quota(task_store, task, team_access))
    return paused_tasks


def clear_quota_guard(task: TaskRecord) -> TaskRecord:
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    if "quota_guard" not in structured:
        return task
    structured = dict(structured)
    structured.pop("quota_guard", None)
    task.structured_requirements = structured
    return task


def _task_creator(task: TaskRecord) -> str:
    return task.creator_user_id or task.created_by
