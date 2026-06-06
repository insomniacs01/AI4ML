from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    HumanInteractionDecisionAction,
    HumanInteractionRequestStatus,
    InteractionTriggerMode,
    TaskAgentCollaborationResponse,
    TaskHumanCollaborationResponse,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskRecord,
    TaskStatus,
)
from backend.app.services.task_agent_collaboration import build_task_agent_collaboration_response
from backend.app.services.service_registry import get_task_human_collaboration_service, get_task_store
from backend.app.services.task_codex_sync import sync_codex_task_state
from backend.app.services.task_human_policy import (
    _apply_interaction_policies,
    _get_current_policy_cycle,
    _load_team_members_for_human,
)
from backend.app.services.task_routing import (
    _build_runtime_context,
    _build_stage_selection_map,
)
from backend.app.services.task_workflow_tracking import (
    _ensure_agent_runtime_records,
    _raise_agent_schema_http_error,
    _sync_task_human_collaboration,
)

router = APIRouter(tags=["task-human"])


def _refresh_codex_task_for_human_snapshot(task: TaskRecord, team_access: TeamAccessContext) -> TaskRecord:
    if task.executor_type != "codex" or not task.codex_workspace_path:
        return task
    task_store = get_task_store()
    refreshed_task, _artifacts = sync_codex_task_state(
        task,
        get_settings(),
        task_store=task_store,
        access_token=team_access.access_token,
        fail_on_error=False,
    )
    if task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human} and refreshed_task.status == TaskStatus.running:
        for request in task_store.list_human_requests(
            refreshed_task.team_id,
            refreshed_task.id,
            access_token=team_access.access_token,
        ):
            payload = request.payload if isinstance(request.payload, dict) else {}
            request_status = str(request.status.value if hasattr(request.status, "value") else request.status)
            if payload.get("request_type") in {"codex_plan_approval", "codex_improvement_review"} and request_status in {"pending", "open"}:
                request.status = HumanInteractionRequestStatus.resolved
                request.decision = {
                    "action": "auto_resolved",
                    "summary": "Codex 已进入运行状态，旧的人工确认请求自动关闭。",
                }
                task_store.update_human_request(request, access_token=team_access.access_token)
    return refreshed_task


@router.get("/{task_id}/human-collaboration", response_model=TaskHumanCollaborationResponse)
def get_task_human_collaboration(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    task = _refresh_codex_task_for_human_snapshot(task, team_access)
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
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        original_request = task_store.get_human_request(
            team_access.team_id,
            task_id,
            request_id,
            access_token=team_access.access_token,
        )
        original_request_payload = original_request.payload if original_request and isinstance(original_request.payload, dict) else {}
        is_codex_plan_approval = original_request_payload.get("request_type") == "codex_plan_approval"
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
        should_advance_checkpoint = (
            payload.resume_task
            and payload.action in {HumanInteractionDecisionAction.approve, HumanInteractionDecisionAction.skip}
            and snapshot.open_request_count == 0
            and not is_codex_plan_approval
        )
        if should_advance_checkpoint:
            runtime_context = _build_runtime_context(team_access)
            stage_selection_map = _build_stage_selection_map(snapshot.task, team_access, runtime_context)
            next_task, created_checkpoint_count = _apply_interaction_policies(
                snapshot.task,
                team_access,
                trigger_mode=InteractionTriggerMode.before_run,
                cycle_id=_get_current_policy_cycle(snapshot.task),
                stage_selection_map=stage_selection_map,
                checkpoint_only=True,
            )
            if created_checkpoint_count:
                _sync_task_human_collaboration(next_task, team_access, stage_selection_map=stage_selection_map)
                snapshot = get_task_human_collaboration_service().get_snapshot(
                    next_task,
                    access_token=team_access.access_token,
                    actor_id=team_access.user.id,
                    actor_role=team_access.role,
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
        return snapshot
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
