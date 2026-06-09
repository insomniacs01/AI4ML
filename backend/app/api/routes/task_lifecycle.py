from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    TaskCompactListItemRecord,
    TaskCreateRequest,
    TaskDeleteResponse,
    TaskListResponse,
    TaskRecord,
    TaskSummaryRecord,
    TaskStatus,
)
from backend.app.services.task_codex_sync import sync_codex_task_state
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_routing import _validate_task_stage_routing_overrides
from backend.app.services.platform_limits import PlatformLimitError, assert_user_can_create_task
from backend.app.services.task_human_policy import validate_interaction_policy_assignees
from backend.app.services.task_workflow_tracking import _sync_task_human_collaboration

router = APIRouter(tags=["task-lifecycle"])
TASK_SUMMARY_NAME_MAX_CHARS = 120
RUNTIME_TASK_STATUSES = (
    TaskStatus.running.value,
    TaskStatus.waiting_human.value,
    TaskStatus.paused_for_review.value,
    TaskStatus.planning.value,
    TaskStatus.uploaded.value,
)


class TaskCacheWarmupResponse(BaseModel):
    warmed: bool
    task_count: int = 0
    detail_task_id: str | None = None


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
        raise_store_http_error(exc)
    return TaskCacheWarmupResponse(warmed=True, task_count=len(tasks), detail_task_id=detail_task_id)


@router.get("", response_model=TaskListResponse, response_model_exclude_none=True)
def list_tasks(
    runtime_only: bool = Query(False),
    compact: bool = Query(False),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskListResponse:
    try:
        task_store = get_task_store()
        items = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            statuses=RUNTIME_TASK_STATUSES if runtime_only else None,
            limit=20 if runtime_only else 100,
            allow_stale_cache=True,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    if compact:
        return TaskListResponse(items=[_compact_task_summary(item) for item in items])
    return TaskListResponse(items=[_task_summary(item) for item in items])


def _task_summary(task: TaskRecord) -> TaskSummaryRecord:
    payload = task.model_dump()
    payload["name"] = _truncate_summary_text(payload.get("name"), TASK_SUMMARY_NAME_MAX_CHARS)
    return TaskSummaryRecord.model_validate(payload)


def _compact_task_summary(task: TaskRecord) -> TaskCompactListItemRecord:
    return TaskCompactListItemRecord(
        id=task.id,
        created_by=task.created_by,
        name=_truncate_summary_text(task.name, TASK_SUMMARY_NAME_MAX_CHARS) or "",
        label_column=task.label_column,
        problem_type=task.problem_type,
        status=task.status,
        dataset_filename=task.dataset_filename,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _truncate_summary_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit]


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
        raise_store_http_error(exc)

    task = task_store.create_task(
        payload,
        team_id=team_access.team_id,
        created_by=team_access.user.id,
        access_token=team_access.access_token,
    )
    _sync_task_human_collaboration(task, team_access, stage_selection_map={})
    return task


@router.get("/{task_id}", response_model=TaskRecord)
def get_task(
    task_id: str,
    sync: bool = Query(True),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    try:
        task = get_task_store().get_task(
            team_access.team_id,
            task_id,
            access_token=team_access.access_token,
            prefer_cache=not sync,
            allow_stale_cache=not sync,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    task.executor_type = "codex"
    if not sync or task.status == TaskStatus.completed:
        return task
    task, _artifacts = sync_codex_task_state(
        task,
        get_settings(),
        task_store=get_task_store(),
        access_token=team_access.access_token,
        fail_on_error=False,
    )
    return task


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
