from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    TaskRecord,
    TaskRunProgressResponse,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.codex_backend import (
    CodexBackendError,
    build_codex_run_progress,
    interrupt_codex_task,
)
from backend.app.services.task_codex_sync import sync_codex_task_state
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_runtime_activity import (
    ActiveCodexTaskConflict,
    ensure_task_controls_current_codex_activity,
)
from backend.app.services.task_runtime_progress import record_user_paused_stages
from backend.app.services.task_workflow_tracking import _record_stage_selection_map

router = APIRouter(tags=["task-runtime"])


def _assert_codex_task_can_control_current_activity(
    task: TaskRecord,
    team_access: TeamAccessContext,
) -> TaskRecord:
    try:
        return ensure_task_controls_current_codex_activity(task, team_access)
    except ActiveCodexTaskConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{task_id}/run-progress", response_model=TaskRunProgressResponse)
def get_task_run_progress(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRunProgressResponse:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    task, _artifacts = sync_codex_task_state(
        task,
        get_settings(),
        task_store=task_store,
        access_token=team_access.access_token,
    )
    return build_codex_run_progress(task, get_settings())


@router.post("/{task_id}/cancel", response_model=TaskRecord)
def cancel_task(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status == TaskStatus.failed and "用户已取消任务" in (task.notes or ""):
        return task
    if task.status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled, TaskStatus.published}:
        return task

    try:
        response = interrupt_codex_task(task, get_settings(), reason="用户已取消任务。")
        task.codex_session_id = response.get("sessionId") or task.codex_session_id
        task.codex_thread_id = response.get("threadId") or task.codex_thread_id
    except CodexBackendError:
        pass
    task.notes = "用户已取消任务。"
    task.status = TaskStatus.cancelled
    try:
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
    except ConnectionError as exc:
        if "violates check constraint" not in str(exc).lower() and "ai_tasks_status_check" not in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        task.status = TaskStatus.failed
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
    _record_stage_selection_map(
        saved_task,
        team_access,
        stage_selection_map={},
        status_by_stage={
            WorkflowStage.feature_engineering: WorkflowStageStatus.failed,
            WorkflowStage.model_selection: WorkflowStageStatus.failed,
            WorkflowStage.training_validation: WorkflowStageStatus.failed,
            WorkflowStage.report_generation: WorkflowStageStatus.failed,
        },
        summary_by_stage={
            WorkflowStage.feature_engineering: "用户已取消任务，后续特征工程不再继续。",
            WorkflowStage.model_selection: "用户已取消任务，后续模型选择不再继续。",
            WorkflowStage.training_validation: "用户已取消任务，后续训练验证不再继续。",
            WorkflowStage.report_generation: "用户已取消任务，报告不再生成。",
        },
    )
    return saved_task


@router.post("/{task_id}/pause", response_model=TaskRecord)
def pause_task(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled, TaskStatus.published}:
        return task

    task = _assert_codex_task_can_control_current_activity(task, team_access)
    try:
        response = interrupt_codex_task(task, get_settings(), reason="用户已暂停当前 Codex 运行，可继续执行。")
    except CodexBackendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    task.executor_type = "codex"
    task.status = TaskStatus.paused_for_review
    task.codex_session_id = response.get("sessionId") or task.codex_session_id
    task.codex_thread_id = response.get("threadId") or task.codex_thread_id
    task.codex_status = "interrupted"
    task.codex_finished_at = None
    task.notes = "用户已暂停当前 Codex 运行，可继续执行。"
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    codex = structured.get("codex") if isinstance(structured.get("codex"), dict) else {}
    structured["executor_type"] = "codex"
    structured["codex"] = {
        **codex,
        "workspace_path": task.codex_workspace_path,
        "session_id": task.codex_session_id,
        "thread_id": task.codex_thread_id,
        "status": "interrupted",
        "pause_reason": "user_paused",
        "paused_at": now.isoformat(),
        "started_at": task.codex_started_at.isoformat() if task.codex_started_at else None,
        "finished_at": None,
    }
    task.structured_requirements = structured
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_user_paused_stages(saved_task, team_access)
    return saved_task
