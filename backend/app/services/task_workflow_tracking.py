from __future__ import annotations

from fastapi import HTTPException, status

from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import (
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.service_registry import get_task_human_collaboration_service, get_task_store
from backend.app.services.task_agent_collaboration import append_stage_agent_messages
from backend.app.services.task_agent_runtime_bootstrap import build_missing_agent_runtimes
from backend.app.services.task_workflow_agent_records import (
    WorkflowStageTrackingContext,
    build_workflow_stage_tracking_context,
)
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
    tracking_context = build_workflow_stage_tracking_context(
        task,
        stage=stage,
        stage_status=stage_status,
        summary=summary,
        stage_record=stage_record,
    )
    task_store = get_task_store()
    _upsert_workflow_stage_record(
        task_store,
        task,
        team_access,
        tracking_context,
        artifact_refs=artifact_refs,
        log_excerpt=log_excerpt,
    )
    try:
        _record_agent_runtime_activity(
            task_store,
            task,
            team_access,
            tracking_context,
            artifact_refs=artifact_refs,
            log_excerpt=log_excerpt,
        )
    except ConnectionError as exc:
        _raise_agent_schema_http_error(exc)

def _upsert_workflow_stage_record(
    task_store,
    task: TaskRecord,
    team_access: TeamAccessContext,
    tracking_context: WorkflowStageTrackingContext,
    *,
    artifact_refs: list[str] | dict | None,
    log_excerpt: str | None,
) -> None:
    task_store.upsert_stage_record(
        team_id=task.team_id,
        task_id=task.id,
        stage=tracking_context.stage,
        status=tracking_context.stage_status,
        access_token=team_access.access_token,
        selected_connector_id=tracking_context.selected_connector_id,
        model_name=tracking_context.model_name,
        selection_source=tracking_context.selection_source,
        summary=tracking_context.current_task,
        artifact_refs=artifact_refs,
        log_excerpt=log_excerpt,
    )

def _record_agent_runtime_activity(
    task_store,
    task: TaskRecord,
    team_access: TeamAccessContext,
    tracking_context: WorkflowStageTrackingContext,
    *,
    artifact_refs: list[str] | dict | None,
    log_excerpt: str | None,
) -> None:
    task_store.upsert_agent_run(
        team_id=task.team_id,
        task_id=task.id,
        agent_id=tracking_context.agent_id,
        stage=tracking_context.stage,
        name=tracking_context.agent_name,
        role=tracking_context.agent_role,
        short_role=tracking_context.agent_short_role,
        status=tracking_context.stage_status,
        progress=tracking_context.progress,
        current_task=tracking_context.current_task,
        access_token=team_access.access_token,
        selected_connector_id=tracking_context.selected_connector_id,
        model_name=tracking_context.model_name,
        selection_source=tracking_context.selection_source,
        artifact_refs=artifact_refs,
        log_excerpt=log_excerpt,
        worker_id=tracking_context.worker_id,
    )
    task_store.append_agent_event(
        team_id=task.team_id,
        task_id=task.id,
        agent_id=tracking_context.agent_id,
        stage=tracking_context.stage,
        kind="agent",
        status=tracking_context.status_value,
        text=tracking_context.event_text,
        artifact_refs=artifact_refs,
        access_token=team_access.access_token,
    )
    append_stage_agent_messages(
        task_store,
        task,
        access_token=team_access.access_token,
        stage=tracking_context.stage,
        stage_status=tracking_context.stage_status,
        summary=tracking_context.current_task,
        artifact_refs=artifact_refs,
        log_excerpt=log_excerpt,
    )

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
    created_records: list[TaskAgentRuntimeRecord] = []
    for runtime in build_missing_agent_runtimes(
        task_id=task.id,
        stages=stages,
        human_requests=human_requests,
        agent_runs=agent_runs,
    ):
        created_records.append(
            task_store.upsert_agent_run(
                team_id=task.team_id,
                task_id=task.id,
                agent_id=runtime.agent_id,
                stage=runtime.stage,
                name=runtime.name,
                role=runtime.role,
                short_role=runtime.short_role,
                status=runtime.status,
                progress=runtime.progress,
                current_task=runtime.current_task,
                access_token=team_access.access_token,
                selected_connector_id=runtime.selected_connector_id,
                model_name=runtime.model_name,
                selection_source=runtime.selection_source,
                artifact_refs=runtime.artifact_refs,
                log_excerpt=runtime.log_excerpt,
                worker_id=runtime.worker_id,
            )
        )
    return [*agent_runs, *created_records]
