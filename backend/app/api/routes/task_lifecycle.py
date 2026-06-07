from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    TaskCreateRequest,
    TaskDeleteResponse,
    TaskListResponse,
    TaskRecord,
    TaskRuntimeSnapshotResponse,
    TaskSemanticUpdateRequest,
    TaskStatus,
    TaskWorkflowConfigUpdateRequest,
)
from backend.app.services.task_codex_sync import sync_codex_task_state
from backend.app.services.task_semantic_tracking import record_human_semantic_update_stages
from backend.app.services.task_semantics import apply_human_semantic_update
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_routing import (
    _build_runtime_context,
    _build_stage_selection_map,
    _validate_task_stage_routing_overrides,
)
from backend.app.services.platform_limits import PlatformLimitError, assert_user_can_create_task
from backend.app.services.task_human_policy import validate_interaction_policy_assignees
from backend.app.services.task_runtime_snapshot import (
    TaskRuntimeSnapshotNotFound,
    TaskRuntimeSnapshotSyncError,
    build_task_runtime_snapshot_response,
)
from backend.app.services.task_workflow_config import apply_task_workflow_config
from backend.app.services.task_workflow_tracking import _sync_task_human_collaboration

router = APIRouter(tags=["task-lifecycle"])


class TaskCacheWarmupResponse(BaseModel):
    warmed: bool
    task_count: int = 0
    detail_task_id: str | None = None


def _raise_task_store_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

@router.post("/cache/warmup", response_model=TaskCacheWarmupResponse)
def warmup_task_cache(team_access: TeamAccessContext = Depends(require_team_access)) -> TaskCacheWarmupResponse:
    try:
        task_store = get_task_store()
        tasks = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            prefer_cache=False,
        )
        detail_task_id = tasks[0].id if tasks else None
        if detail_task_id:
            task_store.get_task(
                team_access.team_id,
                detail_task_id,
                access_token=team_access.access_token,
                prefer_cache=False,
            )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)
    return TaskCacheWarmupResponse(warmed=True, task_count=len(tasks), detail_task_id=detail_task_id)


@router.get("", response_model=TaskListResponse)
def list_tasks(team_access: TeamAccessContext = Depends(require_team_access)) -> TaskListResponse:
    try:
        task_store = get_task_store()
        items = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            allow_stale_cache=True,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)
    return TaskListResponse(items=items)


@router.post("", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    _validate_task_stage_routing_overrides(payload.stage_routing)
    validate_interaction_policy_assignees(payload.interaction_policies, team_access)
    task_store = get_task_store()
    try:
        tasks = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            lightweight=True,
            prefer_cache=False,
        )
        assert_user_can_create_task(get_settings(), tasks=tasks, user_id=team_access.user.id)
    except PlatformLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)

    task = task_store.create_task(
        payload,
        team_id=team_access.team_id,
        created_by=team_access.user.id,
        access_token=team_access.access_token,
    )
    _sync_task_human_collaboration(task, team_access, stage_selection_map={})
    return task


@router.get("/{task_id}", response_model=TaskRecord)
def get_task(task_id: str, team_access: TeamAccessContext = Depends(require_team_access)) -> TaskRecord:
    try:
        task = get_task_store().get_task(
            team_access.team_id,
            task_id,
            access_token=team_access.access_token,
            allow_stale_cache=True,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    task.executor_type = "codex"
    task, _artifacts = sync_codex_task_state(
        task,
        get_settings(),
        task_store=get_task_store(),
        access_token=team_access.access_token,
        fail_on_error=False,
    )
    return task


@router.get("/{task_id}/runtime-snapshot", response_model=TaskRuntimeSnapshotResponse)
def get_task_runtime_snapshot(
    task_id: str,
    sync: bool = Query(True),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRuntimeSnapshotResponse:
    try:
        return build_task_runtime_snapshot_response(task_id, team_access, sync_runtime=sync)
    except TaskRuntimeSnapshotNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TaskRuntimeSnapshotSyncError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)

@router.put("/{task_id}/workflow-config", response_model=TaskRecord)
def update_task_workflow_config(
    task_id: str,
    payload: TaskWorkflowConfigUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    _validate_task_stage_routing_overrides(payload.stage_routing)
    validate_interaction_policy_assignees(payload.interaction_policies, team_access)
    task = apply_task_workflow_config(task, payload)
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(saved_task, team_access, runtime_context)
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    return saved_task


@router.put("/{task_id}/semantic-analysis", response_model=TaskRecord)
def update_task_semantic_analysis(
    task_id: str,
    payload: TaskSemanticUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    try:
        updated_task = apply_human_semantic_update(
            task,
            payload,
            corrected_by=team_access.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    saved_task = task_store.save_task(updated_task, access_token=team_access.access_token)
    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(saved_task, team_access, runtime_context)
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    record_human_semantic_update_stages(
        saved_task,
        team_access,
        payload=payload,
        stage_selection_map=stage_selection_map,
    )
    return saved_task

@router.post("/{task_id}/analyze", response_model=TaskRecord)
def analyze_task(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    task.executor_type = "codex"
    task.status = TaskStatus.planning if task.dataset_path else TaskStatus.draft
    task.notes = "Codex 会在运行时读取数据并生成计划；当前不再调用独立语义解析。"
    return task_store.save_task(task, access_token=team_access.access_token)

@router.delete("/{task_id}", response_model=TaskDeleteResponse)
def delete_task(task_id: str, team_access: TeamAccessContext = Depends(require_team_access)) -> TaskDeleteResponse:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status == TaskStatus.running and "Agent 自动修复受阻" not in (task.notes or ""):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务仍在运行中，请先取消任务后再删除。",
        )

    deleted = task_store.delete_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    return TaskDeleteResponse(deleted=True, task_id=task_id)
