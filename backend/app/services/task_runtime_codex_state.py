from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.quota_runtime_guard import clear_quota_guard


CODEX_START_NOTE = "Codex 正在创建任务工作区并生成建模计划。"
CODEX_PLAN_REGENERATION_NOTE = "Codex 正在根据人工反馈重新生成建模计划。"
CODEX_PLAN_APPROVAL_NOTE = "Codex 已收到计划确认，正在继续执行建模流程。"


def apply_codex_start_response(
    task: TaskRecord,
    response: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> TaskRecord:
    task = _apply_codex_running_response(task, response, notes=CODEX_START_NOTE)
    task.codex_workspace_path = response.get("workspacePath") or task.codex_workspace_path
    task.codex_started_at = task.codex_started_at or now or datetime.now(timezone.utc)
    task.codex_finished_at = None
    task.last_run = None
    task.last_run_attempt = None
    return task


def apply_codex_plan_regeneration_response(
    task: TaskRecord,
    response: Mapping[str, Any],
) -> TaskRecord:
    task = clear_quota_guard(task)
    return _apply_codex_running_response(task, response, notes=CODEX_PLAN_REGENERATION_NOTE)


def apply_codex_resume_response(
    task: TaskRecord,
    response: Mapping[str, Any],
    *,
    notes: str,
) -> TaskRecord:
    task = clear_quota_guard(task)
    task = _apply_codex_running_response(task, response, notes=notes)
    task.codex_finished_at = None
    return task


def apply_codex_plan_approval_response(
    task: TaskRecord,
    response: Mapping[str, Any],
) -> TaskRecord:
    task = clear_quota_guard(task)
    return _apply_codex_running_response(task, response, notes=CODEX_PLAN_APPROVAL_NOTE)


def _apply_codex_running_response(
    task: TaskRecord,
    response: Mapping[str, Any],
    *,
    notes: str,
) -> TaskRecord:
    task.executor_type = "codex"
    task.codex_session_id = response.get("sessionId") or task.codex_session_id
    task.codex_thread_id = response.get("threadId") or task.codex_thread_id
    task.codex_status = "running"
    task.status = TaskStatus.running
    task.notes = notes
    return task
