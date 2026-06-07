from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import TaskRecord, TaskSemanticUpdateRequest, TaskWorkflowConfigUpdateRequest
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_human_policy import validate_interaction_policy_assignees
from backend.app.services.task_routing import (
    _build_runtime_context,
    _build_stage_selection_map,
    _validate_task_stage_routing_overrides,
)
from backend.app.services.task_semantic_tracking import record_human_semantic_update_stages
from backend.app.services.task_semantics import apply_human_semantic_update
from backend.app.services.task_workflow_config import apply_task_workflow_config
from backend.app.services.task_workflow_tracking import _sync_task_human_collaboration


router = APIRouter(tags=["task-lifecycle"])


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
