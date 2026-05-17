from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    TaskAgentCollaborationResponse,
    TaskHumanCollaborationResponse,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    normalize_workflow_stage,
)
from backend.app.services.task_agent_collaboration import build_task_agent_collaboration_response
from backend.app.api.routes.task_route_common import (
    _build_runtime_context,
    _build_stage_selection_map,
    _ensure_agent_runtime_records,
    _load_team_members_for_human,
    _raise_agent_schema_http_error,
    _sync_task_human_collaboration,
    _write_task_audit,
    get_task_human_collaboration_service,
    get_task_store,
)

router = APIRouter(tags=["task-human"])

@router.get("/{task_id}/human-collaboration", response_model=TaskHumanCollaborationResponse)
def get_task_human_collaboration(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(task, team_access, runtime_context)
    _sync_task_human_collaboration(task, team_access, stage_selection_map=stage_selection_map)
    refreshed_task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token) or task
    return get_task_human_collaboration_service().get_snapshot(
        refreshed_task,
        access_token=team_access.access_token,
        actor_id=team_access.user.id,
        actor_role=team_access.role,
    )


@router.get("/{task_id}/agent-collaboration", response_model=TaskAgentCollaborationResponse)
def get_task_agent_collaboration(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskAgentCollaborationResponse:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(task, team_access, runtime_context)
    _sync_task_human_collaboration(task, team_access, stage_selection_map=stage_selection_map)
    refreshed_task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token) or task
    stages = task_store.list_stage_records(team_access.team_id, task_id, access_token=team_access.access_token)
    requests = task_store.list_human_requests(team_access.team_id, task_id, access_token=team_access.access_token)
    try:
        agent_runs = task_store.list_agent_runs(team_access.team_id, task_id, access_token=team_access.access_token)
        agent_runs = _ensure_agent_runtime_records(
            refreshed_task,
            team_access,
            stages=stages,
            human_requests=requests,
            agent_runs=agent_runs,
        )
        agent_events = task_store.list_agent_events(team_access.team_id, task_id, access_token=team_access.access_token)
        agent_messages = task_store.list_agent_messages(team_access.team_id, task_id, access_token=team_access.access_token)
    except ConnectionError as exc:
        _raise_agent_schema_http_error(exc)
    return build_task_agent_collaboration_response(
        refreshed_task,
        stages=stages,
        requests=requests,
        agent_runs=agent_runs,
        agent_events=agent_events,
        agent_messages=agent_messages,
    )


@router.post("/{task_id}/human-requests", response_model=TaskHumanCollaborationResponse, status_code=status.HTTP_201_CREATED)
def create_task_human_request(
    task_id: str,
    payload: TaskHumanRequestCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        team_members = _load_team_members_for_human(team_access)
        snapshot = get_task_human_collaboration_service().create_request(
            task,
            payload,
            requested_by=team_access.user.id,
            actor_role=team_access.role,
            team_members=team_members,
            access_token=team_access.access_token,
        )
        _write_task_audit(
            team_access,
            action="task.human_request.create",
            task_id=task.id,
            detail={
                "request_type": payload.request_type,
                "stage": normalize_workflow_stage(payload.stage).value,
                "assigned_to": payload.assigned_to,
                "assignee_type": payload.assignee_type.value if payload.assignee_type else None,
                "assignee_value": payload.assignee_value,
            },
        )
        return snapshot
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/human-requests/{request_id}/decision", response_model=TaskHumanCollaborationResponse)
def decide_task_human_request(
    task_id: str,
    request_id: str,
    payload: TaskHumanRequestDecisionRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        team_members = _load_team_members_for_human(team_access)
        snapshot = get_task_human_collaboration_service().submit_decision(
            task,
            request_id,
            payload,
            decided_by=team_access.user.id,
            actor_role=team_access.role,
            team_members=team_members,
            access_token=team_access.access_token,
        )
        _write_task_audit(
            team_access,
            action="task.human_request.decide",
            task_id=task.id,
            detail={
                "request_id": request_id,
                "action": payload.action.value,
                "reassign_assignee_type": payload.reassign_assignee_type.value if payload.reassign_assignee_type else None,
                "reassign_assignee_value": payload.reassign_assignee_value,
                "reassign_assigned_to": payload.reassign_assigned_to,
            },
        )
        return snapshot
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/resume", response_model=TaskHumanCollaborationResponse)
def resume_task_after_human_collaboration(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        snapshot = get_task_human_collaboration_service().resume_task(
            task,
            access_token=team_access.access_token,
            actor_id=team_access.user.id,
            actor_role=team_access.role,
        )
        _write_task_audit(
            team_access,
            action="task.resume",
            task_id=task.id,
            detail={"status": snapshot.task.status.value},
        )
        return snapshot
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
