from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.config import Settings, get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    TaskRecord,
    TaskRunProgressResponse,
    TaskRunRequest,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.codex_backend import (
    CodexBackendError,
    approve_codex_plan,
    build_codex_run_progress,
    codex_plan_text,
    interrupt_codex_task,
    regenerate_codex_plan,
    resume_codex_task,
    start_codex_task,
)
from backend.app.services.task_codex_sync import sync_codex_task_state
from backend.app.services.task_human_parameter_guidance import resolve_task_run_time_limit
from backend.app.services.service_registry import get_task_human_collaboration_service, get_task_store
from backend.app.services.platform_limits import (
    PlatformLimitError,
    assert_time_budget_within_limit,
    assert_user_can_start_task,
)
from backend.app.services.quota_runtime_guard import clear_quota_guard, quota_token_budget
from backend.app.services.task_routing import _assert_quota_allows_action
from backend.app.services.task_runtime_activity import (
    ActiveCodexTaskConflict,
    ensure_task_controls_current_codex_activity,
)
from backend.app.services.task_runtime_codex_state import (
    apply_codex_plan_approval_response,
    apply_codex_plan_regeneration_response,
    apply_codex_resume_response,
    apply_codex_start_response,
)
from backend.app.services.task_codex_human_requests import ensure_codex_plan_request
from backend.app.services.task_codex_metadata import update_codex_structured_metadata
from backend.app.services.task_runtime_progress import (
    record_codex_running_stages,
    record_codex_status_stages,
    record_user_paused_stages,
)
from backend.app.services.task_runtime_resume import (
    codex_interrupted,
    codex_waiting_improvement_review,
    codex_waiting_plan_approval,
    has_open_human_confirmation_requests,
    resume_note_for_improvement_decision,
)
from backend.app.services.task_workflow_tracking import _record_stage_selection_map

router = APIRouter(tags=["task-runtime"])


def _task_requested_time_limit(task: TaskRecord, payload: TaskRunRequest) -> int | None:
    if payload.time_limit is not None:
        return payload.time_limit
    return resolve_task_run_time_limit(task, None)


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

@router.post("/{task_id}/run", response_model=TaskRecord)
def run_task(
    task_id: str,
    payload: TaskRunRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if not task.dataset_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset has not been uploaded")
    try:
        all_tasks = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            lightweight=True,
            prefer_cache=False,
        )
        assert_user_can_start_task(
            get_settings(),
            tasks=all_tasks,
            user_id=team_access.user.id,
            task_id=task.id,
        )
        assert_time_budget_within_limit(get_settings(), _task_requested_time_limit(task, payload))
    except PlatformLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    task.executor_type = "codex"
    return _run_codex_task(task, payload, team_access)


def _run_codex_task(
    task: TaskRecord,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
) -> TaskRecord:
    task_store = get_task_store()
    human_service = get_task_human_collaboration_service()
    settings = get_settings()
    task = _assert_codex_task_can_control_current_activity(task, team_access)

    if payload.regenerate_plan:
        quota = _assert_quota_allows_action(team_access, action_name="Codex 重新生成方案")
        return _regenerate_codex_plan_and_save(
            task,
            team_access,
            settings,
            token_budget=quota_token_budget(quota),
        )

    if payload.resume_interrupted:
        quota = _assert_quota_allows_action(team_access, action_name="Codex 继续运行")
        return _resume_interrupted_codex_task(
            task,
            payload,
            team_access,
            settings,
            token_budget=quota_token_budget(quota),
        )

    if payload.resume_after_human:
        quota = _assert_quota_allows_action(team_access, action_name="Codex 继续运行")
        return _approve_codex_plan_and_save(
            task,
            payload,
            team_access,
            settings,
            token_budget=quota_token_budget(quota),
        )

    try:
        human_service.assert_task_can_run(task, access_token=team_access.access_token)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    quota = _assert_quota_allows_action(team_access, action_name="Codex 运行")
    task = clear_quota_guard(task)

    if task.status == TaskStatus.running and task.codex_workspace_path:
        task, artifacts = sync_codex_task_state(task, settings)
        return _save_codex_sync_result(task, artifacts, team_access)
    if task.status == TaskStatus.running:
        return task

    if task.codex_workspace_path:
        task, artifacts = sync_codex_task_state(task, settings)
        if task.status in {TaskStatus.paused_for_review, TaskStatus.completed, TaskStatus.failed}:
            return _save_codex_sync_result(task, artifacts, team_access)

    return _start_codex_task_and_save(
        task,
        team_access,
        settings,
        token_budget=quota_token_budget(quota),
    )


def _regenerate_codex_plan_and_save(
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Settings,
    *,
    token_budget: int | None,
) -> TaskRecord:
    task_store = get_task_store()
    try:
        response = regenerate_codex_plan(task, settings, token_budget=token_budget)
    except CodexBackendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    task = apply_codex_plan_regeneration_response(task, response)
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_running_stages(saved_task, team_access)
    return saved_task


def _save_codex_sync_result(
    task: TaskRecord,
    artifacts: dict,
    team_access: TeamAccessContext,
) -> TaskRecord:
    task_store = get_task_store()
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_status_stages(saved_task, team_access, artifacts)
    return saved_task


def _start_codex_task_and_save(
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Settings,
    *,
    token_budget: int | None,
) -> TaskRecord:
    task_store = get_task_store()
    try:
        response = start_codex_task(task, settings, token_budget=token_budget)
    except CodexBackendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    task = apply_codex_start_response(task, response)
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_running_stages(saved_task, team_access)
    return saved_task


def _resume_interrupted_codex_task(
    task: TaskRecord,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
    settings: Settings,
    *,
    token_budget: int | None,
) -> TaskRecord:
    if not task.codex_workspace_path:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Codex workspace is not available.")
    task, artifacts = sync_codex_task_state(task, settings)
    progress = artifacts.get("progress") if isinstance(artifacts.get("progress"), dict) else {}
    if codex_waiting_plan_approval(task, progress):
        return _approve_codex_plan_and_save(
            task,
            payload,
            team_access,
            settings,
            token_budget=token_budget,
        )
    if codex_waiting_improvement_review(task, progress):
        return _resume_codex_task_and_save(
            task,
            team_access,
            settings,
            token_budget=token_budget,
            improvement_decision=payload.improvement_decision or "continue_improvement",
        )
    if not codex_interrupted(task, progress):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务不是已暂停状态，不能按中断恢复。")
    return _resume_codex_task_and_save(
        task,
        team_access,
        settings,
        token_budget=token_budget,
        improvement_decision=payload.improvement_decision,
    )


def _resume_codex_task_and_save(
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Settings,
    *,
    token_budget: int | None,
    improvement_decision: str | None,
) -> TaskRecord:
    task_store = get_task_store()
    if improvement_decision:
        requests = task_store.list_human_requests(task.team_id, task.id, access_token=team_access.access_token)
        if has_open_human_confirmation_requests(requests):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There are open human confirmation requests.")
    try:
        response = resume_codex_task(
            task,
            settings,
            token_budget=token_budget,
            improvement_decision=improvement_decision,
        )
    except CodexBackendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    task = apply_codex_resume_response(
        task,
        response,
        notes=resume_note_for_improvement_decision(improvement_decision),
    )
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_running_stages(saved_task, team_access)
    return saved_task


def _approve_codex_plan_and_save(
    task: TaskRecord,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
    settings: Settings,
    *,
    token_budget: int | None,
) -> TaskRecord:
    task_store = get_task_store()
    requests = task_store.list_human_requests(task.team_id, task.id, access_token=team_access.access_token)
    if has_open_human_confirmation_requests(requests):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There are open human confirmation requests.")
    plan_text = payload.plan_text or codex_plan_text(task, settings)
    if not plan_text.strip():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Codex plan is not ready for approval")
    try:
        response = approve_codex_plan(task, settings, plan_text=plan_text, token_budget=token_budget)
    except CodexBackendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    task = apply_codex_plan_approval_response(task, response)
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_running_stages(saved_task, team_access)
    return saved_task
