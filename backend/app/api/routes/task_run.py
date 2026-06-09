from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.config import Settings, get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import TaskRecord, TaskRunRequest, TaskStatus
from backend.app.services.codex_backend import (
    CodexBackendError,
    approve_codex_plan,
    codex_plan_text,
    regenerate_codex_plan,
    resume_codex_task,
    start_codex_task,
)
from backend.app.services.platform_limits import PlatformLimitError
from backend.app.services.quota_runtime_guard import clear_quota_guard, quota_token_budget
from backend.app.services.service_registry import get_task_human_collaboration_service, get_task_store
from backend.app.services.task_codex_metadata import update_codex_structured_metadata
from backend.app.services.task_codex_plan_approval import (
    CodexPlanNotReadyError,
    assert_codex_plan_ready_for_approval,
)
from backend.app.services.task_codex_sync import sync_codex_task_state
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
from backend.app.services.task_runtime_progress import record_codex_running_stages, record_codex_status_stages
from backend.app.services.task_runtime_resume import (
    codex_interrupted,
    codex_waiting_improvement_review,
    codex_waiting_plan_approval,
    has_open_human_confirmation_requests,
    resume_note_for_improvement_decision,
)
from backend.app.services.task_run_preflight import assert_task_run_preflight


router = APIRouter(tags=["task-runtime"])


def _assert_codex_task_can_control_current_activity(
    task: TaskRecord,
    team_access: TeamAccessContext,
) -> TaskRecord:
    try:
        return ensure_task_controls_current_codex_activity(task, team_access)
    except ActiveCodexTaskConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/run", response_model=TaskRecord)
def run_task_endpoint(
    task_id: str,
    payload: TaskRunRequest,
    background_tasks: BackgroundTasks,
    async_start: bool = Query(default=False),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    return run_task(
        task_id,
        payload,
        team_access,
        background_tasks=background_tasks,
        async_start=async_start,
    )


def run_task(
    task_id: str,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
    background_tasks: BackgroundTasks | None = None,
    async_start: bool = False,
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if not task.dataset_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset has not been uploaded")
    try:
        assert_task_run_preflight(task_store, task, payload, team_access, settings=get_settings())
    except PlatformLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

    task.executor_type = "codex"
    return _run_codex_task(
        task,
        payload,
        team_access,
        background_tasks=background_tasks,
        async_start=async_start,
    )


def _run_codex_task(
    task: TaskRecord,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
    *,
    background_tasks: BackgroundTasks | None = None,
    async_start: bool = False,
) -> TaskRecord:
    task_store = get_task_store()
    human_service = get_task_human_collaboration_service()
    settings = get_settings()
    task = _assert_codex_task_can_control_current_activity(task, team_access)

    if payload.regenerate_plan:
        quota = _assert_quota_allows_action(team_access, action_name="Codex 重新生成方案")
        token_budget = quota_token_budget(quota)
        if async_start and background_tasks is not None:
            return _queue_codex_continue_and_save(
                task,
                payload,
                team_access,
                settings,
                background_tasks,
                action="regenerate_plan",
                token_budget=token_budget,
                note="Codex 正在后台根据人工反馈重新生成建模计划。",
            )
        return _regenerate_codex_plan_and_save(
            task,
            team_access,
            settings,
            token_budget=token_budget,
        )

    if payload.resume_interrupted:
        quota = _assert_quota_allows_action(team_access, action_name="Codex 继续运行")
        token_budget = quota_token_budget(quota)
        if async_start and background_tasks is not None:
            return _queue_codex_continue_and_save(
                task,
                payload,
                team_access,
                settings,
                background_tasks,
                action="resume_interrupted",
                token_budget=token_budget,
                note="Codex 正在后台恢复任务执行。",
            )
        return _resume_interrupted_codex_task(
            task,
            payload,
            team_access,
            settings,
            token_budget=token_budget,
        )

    if payload.resume_after_human:
        quota = _assert_quota_allows_action(team_access, action_name="Codex 继续运行")
        token_budget = quota_token_budget(quota)
        if async_start and background_tasks is not None:
            return _queue_codex_continue_and_save(
                task,
                payload,
                team_access,
                settings,
                background_tasks,
                action="resume_after_human",
                token_budget=token_budget,
                note="Codex 正在后台接收人工确认并继续执行。",
            )
        return _approve_codex_plan_and_save(
            task,
            payload,
            team_access,
            settings,
            token_budget=token_budget,
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

    token_budget = quota_token_budget(quota)
    if async_start and background_tasks is not None:
        return _queue_codex_start_and_save(
            task,
            team_access,
            settings,
            background_tasks,
            token_budget=token_budget,
        )
    return _start_codex_task_and_save(task, team_access, settings, token_budget=token_budget)


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


def _queue_codex_start_and_save(
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Settings,
    background_tasks: BackgroundTasks,
    *,
    token_budget: int | None,
) -> TaskRecord:
    task_store = get_task_store()
    task.executor_type = "codex"
    task.status = TaskStatus.running
    task.codex_status = "starting"
    task.notes = "Codex 正在后台创建任务工作区并生成建模计划。"
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_running_stages(saved_task, team_access)
    background_tasks.add_task(
        _start_codex_task_background,
        saved_task,
        team_access,
        settings,
        token_budget,
    )
    return saved_task


def _start_codex_task_background(
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Settings,
    token_budget: int | None,
) -> None:
    try:
        _start_codex_task_and_save(task, team_access, settings, token_budget=token_budget)
    except Exception as exc:  # Background tasks cannot surface HTTP errors to the original response.
        _save_codex_background_failure(task, team_access, f"Codex 后台启动失败：{exc}")


def _queue_codex_continue_and_save(
    task: TaskRecord,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
    settings: Settings,
    background_tasks: BackgroundTasks,
    *,
    action: str,
    token_budget: int | None,
    note: str,
) -> TaskRecord:
    task_store = get_task_store()
    task_for_background = task.model_copy(deep=True)
    payload_for_background = payload.model_copy(deep=True)
    task.executor_type = "codex"
    task.status = TaskStatus.running
    task.codex_status = "starting"
    task.notes = note
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_running_stages(saved_task, team_access)
    background_tasks.add_task(
        _continue_codex_task_background,
        action,
        task_for_background,
        payload_for_background,
        team_access,
        settings,
        token_budget,
        saved_task,
    )
    return saved_task


def _continue_codex_task_background(
    action: str,
    task: TaskRecord,
    payload: TaskRunRequest,
    team_access: TeamAccessContext,
    settings: Settings,
    token_budget: int | None,
    queued_task: TaskRecord,
) -> None:
    try:
        if action == "regenerate_plan":
            _regenerate_codex_plan_and_save(task, team_access, settings, token_budget=token_budget)
            return
        if action == "resume_interrupted":
            _resume_interrupted_codex_task(task, payload, team_access, settings, token_budget=token_budget)
            return
        if action == "resume_after_human":
            _approve_codex_plan_and_save(task, payload, team_access, settings, token_budget=token_budget)
            return
        raise RuntimeError(f"unsupported Codex background action: {action}")
    except Exception as exc:  # Background tasks cannot surface HTTP errors to the original response.
        _save_codex_background_failure(queued_task, team_access, f"Codex 后台继续执行失败：{exc}")


def _save_codex_background_failure(
    task: TaskRecord,
    team_access: TeamAccessContext,
    note: str,
) -> None:
    task.status = TaskStatus.failed
    task.codex_status = "failed"
    task.notes = note
    task = update_codex_structured_metadata(task)
    get_task_store().save_task(task, access_token=team_access.access_token)


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
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="There are open human confirmation requests.",
            )
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="There are open human confirmation requests.",
        )
    plan_text = payload.plan_text or codex_plan_text(task, settings)
    try:
        assert_codex_plan_ready_for_approval(plan_text)
    except CodexPlanNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    try:
        response = approve_codex_plan(task, settings, plan_text=plan_text, token_budget=token_budget)
    except CodexBackendError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    task = apply_codex_plan_approval_response(task, response)
    task = update_codex_structured_metadata(task)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    record_codex_running_stages(saved_task, team_access)
    return saved_task
