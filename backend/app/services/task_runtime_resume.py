from __future__ import annotations

from collections.abc import Iterable

from backend.app.models.task import HumanInteractionRequestStatus, TaskHumanRequestRecord, TaskRecord


CODEX_INTERRUPTED_STATUSES = {"interrupted"}
CODEX_PLAN_APPROVAL_STATUSES = {"waiting_plan_approval", "plan_ready", "awaiting_plan_approval"}
CODEX_IMPROVEMENT_REVIEW_STATUSES = {
    "waiting_improvement_review",
    "improvement_review",
    "waiting_improvement_approval",
}
OPEN_HUMAN_REQUEST_STATUSES = {
    HumanInteractionRequestStatus.pending.value,
    HumanInteractionRequestStatus.open.value,
}


def codex_interrupted(task: TaskRecord, progress: dict[str, object]) -> bool:
    return any(
        status_value(value) in CODEX_INTERRUPTED_STATUSES
        for value in (task.codex_status, progress.get("status"))
    )


def codex_waiting_plan_approval(task: TaskRecord, progress: dict[str, object]) -> bool:
    return task_or_progress_has_status(task, progress, CODEX_PLAN_APPROVAL_STATUSES)


def codex_waiting_improvement_review(task: TaskRecord, progress: dict[str, object]) -> bool:
    return task_or_progress_has_status(task, progress, CODEX_IMPROVEMENT_REVIEW_STATUSES)


def has_open_human_confirmation_requests(requests: Iterable[TaskHumanRequestRecord]) -> bool:
    return any(status_value(item.status) in OPEN_HUMAN_REQUEST_STATUSES for item in requests)


def resume_note_for_improvement_decision(improvement_decision: str | None) -> str:
    if improvement_decision == "continue_improvement":
        return "Codex 已按用户选择继续执行改进方案。"
    if improvement_decision == "stop_and_report":
        return "Codex 已按用户选择停止继续改进，正在生成当前结果报告。"
    return "Codex 已从暂停位置继续执行。"


def task_or_progress_has_status(
    task: TaskRecord,
    progress: dict[str, object],
    statuses: set[str],
) -> bool:
    values = [
        task.codex_status,
        progress.get("status"),
        progress.get("current_step"),
    ]
    if any(status_value(value) in statuses for value in values):
        return True
    steps = progress.get("steps")
    if isinstance(steps, list):
        for item in steps:
            if not isinstance(item, dict):
                continue
            step_values = (item.get("id"), item.get("name"), item.get("status"))
            if any(status_value(value) in statuses for value in step_values):
                return True
    return False


def status_value(value: object) -> str:
    return str(value.value if hasattr(value, "value") else value or "").strip().lower()
