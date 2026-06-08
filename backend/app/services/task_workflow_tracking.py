from __future__ import annotations

from fastapi import HTTPException, status

from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.service_registry import get_task_human_collaboration_service, get_task_store
from backend.app.services.task_agent_collaboration import append_stage_agent_messages
from backend.app.services.task_agent_definitions import agent_runtime_spec_for_stage
from backend.app.services.task_agent_status import agent_progress_for_status, agent_status_label
from backend.app.services.task_human_request_status import human_request_is_active


from backend.app.services.task_routing import _ResolvedStageSelection

AGENT_SCHEMA_MISSING_DETAIL = (
    "Supabase schema is missing agent collaboration tables. "
    "Run the latest supabase/schema.sql and wait for the PostgREST schema cache to refresh."
)

def _sync_task_human_collaboration(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stage_selection_map: dict[str, TaskStageRoutingRecord] | None = None,
) -> None:
    get_task_human_collaboration_service().sync_task_stages(
        task,
        access_token=team_access.access_token,
        stage_selection_map=stage_selection_map,
    )

def _is_agent_schema_missing_error(exc: Exception) -> bool:
    text = str(exc)
    return "PGRST205" in text and any(
        table_name in text
        for table_name in ("task_agent_runs", "task_agent_events", "task_agent_messages")
    )

def _raise_agent_schema_http_error(exc: Exception) -> None:
    if _is_agent_schema_missing_error(exc):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AGENT_SCHEMA_MISSING_DETAIL) from exc
    raise exc

def _is_agent_schema_http_exception(exc: HTTPException) -> bool:
    return exc.status_code == status.HTTP_409_CONFLICT and str(exc.detail) == AGENT_SCHEMA_MISSING_DETAIL

def _record_workflow_stage(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stage: WorkflowStage,
    stage_status: WorkflowStageStatus,
    summary: str,
    selection: TaskStageRoutingRecord | _ResolvedStageSelection | None = None,
    artifact_refs: list[str] | dict | None = None,
    log_excerpt: str | None = None,
) -> None:
    stage_record = selection.stage_record if isinstance(selection, _ResolvedStageSelection) else selection
    task_store = get_task_store()
    task_store.upsert_stage_record(
        team_id=task.team_id,
        task_id=task.id,
        stage=stage,
        status=stage_status,
        access_token=team_access.access_token,
        selected_connector_id=stage_record.connector_id if stage_record else None,
        model_name=stage_record.model_name if stage_record else None,
        selection_source=stage_record.selection_source if stage_record else None,
        summary=summary,
        artifact_refs=artifact_refs,
        log_excerpt=log_excerpt,
    )
    agent_spec = agent_runtime_spec_for_stage(stage)
    agent_name = str(agent_spec["name"])
    agent_role = str(agent_spec["role"])
    status_value = stage_status.value if hasattr(stage_status, "value") else str(stage_status)
    current_task = summary
    try:
        task_store.upsert_agent_run(
            team_id=task.team_id,
            task_id=task.id,
            agent_id=str(agent_spec["agent_id"]),
            stage=stage,
            name=agent_name,
            role=agent_role,
            short_role=str(agent_spec["short_role"]),
            status=stage_status,
            progress=agent_progress_for_status(stage_status),
            current_task=current_task,
            access_token=team_access.access_token,
            selected_connector_id=stage_record.connector_id if stage_record else None,
            model_name=stage_record.model_name if stage_record else None,
            selection_source=stage_record.selection_source if stage_record else None,
            artifact_refs=artifact_refs,
            log_excerpt=log_excerpt,
            worker_id=f"backend-agent-worker:{task.id}:{normalize_workflow_stage(stage).value}",
        )
        task_store.append_agent_event(
            team_id=task.team_id,
            task_id=task.id,
            agent_id=str(agent_spec["agent_id"]),
            stage=stage,
            kind="agent",
            status=status_value,
            text=f"{agent_name}（{agent_role}）{agent_status_label(stage_status)}：{current_task}",
            artifact_refs=artifact_refs,
            access_token=team_access.access_token,
        )
        append_stage_agent_messages(
            task_store,
            task,
            access_token=team_access.access_token,
            stage=stage,
            stage_status=stage_status,
            summary=current_task,
            artifact_refs=artifact_refs,
            log_excerpt=log_excerpt,
        )
    except ConnectionError as exc:
        _raise_agent_schema_http_error(exc)

def _record_stage_selection_map(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stage_selection_map: dict[str, TaskStageRoutingRecord],
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus],
    summary_by_stage: dict[WorkflowStage, str],
    artifact_refs: list[str] | dict | None = None,
    artifact_refs_by_stage: dict[WorkflowStage, list[str] | dict] | None = None,
    log_excerpt_by_stage: dict[WorkflowStage, str] | None = None,
) -> None:
    for stage, stage_status in status_by_stage.items():
        _record_workflow_stage(
            task,
            team_access,
            stage=stage,
            stage_status=stage_status,
            summary=summary_by_stage[stage],
            selection=stage_selection_map.get(stage.value),
            artifact_refs=artifact_refs_by_stage.get(stage, artifact_refs) if artifact_refs_by_stage else artifact_refs,
            log_excerpt=log_excerpt_by_stage.get(stage) if log_excerpt_by_stage else None,
        )

def _ensure_agent_runtime_records(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stages: list[WorkflowStageRecord],
    human_requests: list[TaskHumanRequestRecord],
    agent_runs: list[TaskAgentRuntimeRecord],
) -> list[TaskAgentRuntimeRecord]:
    task_store = get_task_store()
    existing_by_agent = {record.agent_id: record for record in agent_runs}
    stages_by_key = {normalize_workflow_stage(record.stage).value: record for record in stages}
    open_request_stages = {
        normalize_workflow_stage(request.stage).value
        for request in human_requests
        if human_request_is_active(request)
    }

    created_records: list[TaskAgentRuntimeRecord] = []
    for stage in PRIMARY_WORKFLOW_STAGES:
        stage_key = stage.value
        if stage_key in existing_by_agent:
            continue
        stage_record = stages_by_key.get(stage_key)
        agent_spec = agent_runtime_spec_for_stage(stage)
        resolved_status = stage_record.status if stage_record else WorkflowStageStatus.pending
        if stage_key in open_request_stages:
            resolved_status = WorkflowStageStatus.waiting_human
        current_task = (
            stage_record.summary
            if stage_record and stage_record.summary
            else str(agent_spec["description"])
        )
        created_records.append(
            task_store.upsert_agent_run(
                team_id=task.team_id,
                task_id=task.id,
                agent_id=stage_key,
                stage=stage,
                name=str(agent_spec["name"]),
                role=str(agent_spec["role"]),
                short_role=str(agent_spec["short_role"]),
                status=resolved_status,
                progress=agent_progress_for_status(resolved_status),
                current_task=current_task,
                access_token=team_access.access_token,
                selected_connector_id=stage_record.selected_connector_id if stage_record else None,
                model_name=stage_record.model_name if stage_record else None,
                selection_source=stage_record.selection_source if stage_record else None,
                artifact_refs=stage_record.artifact_refs if stage_record else None,
                log_excerpt=stage_record.log_excerpt if stage_record else None,
                worker_id=f"backend-agent-worker:{task.id}:{stage_key}",
            )
        )
    return [*agent_runs, *created_records]
