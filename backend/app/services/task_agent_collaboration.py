from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskAgentCollaborationResponse,
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRecord,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_agent_artifacts import flatten_artifact_refs as _flatten_artifact_refs
from backend.app.services.task_agent_definitions import (
    agent_definition as _agent_definition,
    agent_runtime_spec_for_stage,
    progress_for_status as _progress_for_status,
    stage_status_label as _stage_status_label,
)
from backend.app.services.task_agent_messages import build_stage_message_specs as _build_stage_message_specs
from backend.app.services.task_agent_sanitization import (
    sanitize_agent_events as _sanitize_agent_events,
    sanitize_agent_messages as _sanitize_agent_messages,
    sanitize_agent_record as _sanitize_agent_record,
    sanitize_stage_record as _sanitize_stage_record,
)
from backend.app.services.task_human_request_status import human_request_is_active, human_request_status_value


def build_task_agent_collaboration_response(
    task: TaskRecord,
    *,
    stages: list[WorkflowStageRecord],
    requests: list[TaskHumanRequestRecord],
    agent_runs: list[TaskAgentRuntimeRecord] | None = None,
    agent_events: list[TaskAgentEventRecord] | None = None,
    agent_messages: list[TaskAgentMessageRecord] | None = None,
) -> TaskAgentCollaborationResponse:
    stages_by_key = {normalize_workflow_stage(stage.stage).value: stage for stage in stages}
    runs_by_agent = {item.agent_id: item for item in (agent_runs or [])}
    open_request_stages = {
        normalize_workflow_stage(request.stage).value
        for request in requests
        if human_request_is_active(request)
    }

    agents: list[TaskAgentRecord] = []
    for stage in PRIMARY_WORKFLOW_STAGES:
        definition = _agent_definition(stage)
        stage_record = stages_by_key.get(stage.value)
        runtime_record = runs_by_agent.get(stage.value)
        if runtime_record is not None:
            agents.append(
                _agent_from_runtime_record(
                    runtime_record,
                    definition=definition,
                    has_open_request=stage.value in open_request_stages,
                )
            )
            continue

        agents.append(
            _agent_from_stage_record(
                stage,
                stage_record=stage_record,
                definition=definition,
                has_open_request=stage.value in open_request_stages,
            )
        )

    runtime_mode = "persistent_agent_runtime" if agent_runs else "stage_agent_orchestrator"
    safe_stages = [_sanitize_stage_record(stage) for stage in stages]
    safe_agents = [_sanitize_agent_record(agent) for agent in agents]
    safe_events = _sanitize_agent_events(_build_events(safe_agents, requests, agent_events=agent_events if agent_runs else None))
    safe_messages = _sanitize_agent_messages(_sort_messages(agent_messages or []))
    return TaskAgentCollaborationResponse(
        task=task,
        runtime_mode=runtime_mode,
        stages=safe_stages,
        requests=requests,
        agents=safe_agents,
        events=safe_events,
        messages=safe_messages,
    )


def append_stage_agent_messages(
    task_store: Any,
    task: TaskRecord,
    *,
    access_token: str,
    stage: WorkflowStage,
    stage_status: WorkflowStageStatus,
    summary: str,
    artifact_refs: list[str] | dict | None = None,
    log_excerpt: str | None = None,
) -> list[TaskAgentMessageRecord]:
    """Persist real inter-agent messages for a stage transition."""
    messages: list[TaskAgentMessageRecord] = []
    for spec in _build_stage_message_specs(
        stage=stage,
        stage_status=stage_status,
        summary=summary,
        artifact_refs=artifact_refs,
        log_excerpt=log_excerpt,
    ):
        messages.append(
            task_store.append_agent_message(
                team_id=task.team_id,
                task_id=task.id,
                from_agent_id=spec["from_agent_id"],
                to_agent_id=spec.get("to_agent_id"),
                stage=stage,
                message_type=spec["message_type"],
                status="sent",
                content=spec["content"],
                payload=spec["payload"],
                artifact_refs=artifact_refs,
                correlation_id=spec["correlation_id"],
                access_token=access_token,
            )
        )
    return messages


def _resolve_status(
    stage_record: WorkflowStageRecord | None,
    *,
    has_open_request: bool,
) -> WorkflowStageStatus:
    if has_open_request:
        return WorkflowStageStatus.waiting_human
    return stage_record.status if stage_record else WorkflowStageStatus.pending


def _agent_from_runtime_record(
    runtime_record: TaskAgentRuntimeRecord,
    *,
    definition: dict[str, Any],
    has_open_request: bool,
) -> TaskAgentRecord:
    resolved_status = WorkflowStageStatus.waiting_human if has_open_request else runtime_record.status
    artifact_refs = _flatten_artifact_refs(runtime_record.artifact_refs)
    last_action_at = runtime_record.updated_at or runtime_record.finished_at or runtime_record.started_at or runtime_record.created_at
    return TaskAgentRecord(
        id=runtime_record.agent_id,
        stage=normalize_workflow_stage(runtime_record.stage),
        name=runtime_record.name or definition["name"],
        role=runtime_record.role or definition["role"],
        short_role=runtime_record.short_role or definition["short_role"],
        status=resolved_status,
        progress=_progress_for_status(resolved_status) if has_open_request else runtime_record.progress,
        current_task=runtime_record.current_task or definition["description"],
        model_name=runtime_record.model_name,
        connector_id=runtime_record.selected_connector_id,
        selection_source=runtime_record.selection_source,
        artifact_refs=artifact_refs,
        artifact_count=len(artifact_refs),
        last_action_at=last_action_at,
        runtime_id=runtime_record.id,
        runtime_source="persistent_agent_runtime",
        worker_id=runtime_record.worker_id,
        started_at=runtime_record.started_at,
        finished_at=runtime_record.finished_at,
        duration_seconds=runtime_record.duration_seconds,
        log_excerpt=runtime_record.log_excerpt,
        x=definition["x"],
        y=definition["y"],
    )


def _agent_from_stage_record(
    stage: WorkflowStage,
    *,
    stage_record: WorkflowStageRecord | None,
    definition: dict[str, Any],
    has_open_request: bool,
) -> TaskAgentRecord:
    resolved_status = _resolve_status(stage_record, has_open_request=has_open_request)
    artifact_refs = _flatten_artifact_refs(stage_record.artifact_refs if stage_record else None)
    return TaskAgentRecord(
        id=stage.value,
        stage=stage,
        name=definition["name"],
        role=definition["role"],
        short_role=definition["short_role"],
        status=resolved_status,
        progress=_progress_for_status(resolved_status),
        current_task=stage_record.summary if stage_record and stage_record.summary else definition["description"],
        model_name=stage_record.model_name if stage_record else None,
        connector_id=stage_record.selected_connector_id if stage_record else None,
        selection_source=stage_record.selection_source if stage_record else None,
        artifact_refs=artifact_refs,
        artifact_count=len(artifact_refs),
        last_action_at=_last_action_at(stage_record),
        runtime_source="stage_record_projection",
        started_at=stage_record.started_at if stage_record else None,
        finished_at=stage_record.finished_at if stage_record else None,
        duration_seconds=stage_record.duration_seconds if stage_record else None,
        log_excerpt=stage_record.log_excerpt if stage_record else None,
        x=definition["x"],
        y=definition["y"],
    )


def _last_action_at(stage_record: WorkflowStageRecord | None) -> datetime | None:
    if stage_record is None:
        return None
    return stage_record.updated_at or stage_record.finished_at or stage_record.started_at or stage_record.created_at


def _build_events(
    agents: list[TaskAgentRecord],
    requests: list[TaskHumanRequestRecord],
    *,
    agent_events: list[TaskAgentEventRecord] | None = None,
) -> list[TaskAgentEventRecord]:
    events = list(agent_events) if agent_events else _stage_events_from_agents(agents)
    events.extend(_human_request_events(requests))
    return _sort_events(events)


def _stage_events_from_agents(agents: list[TaskAgentRecord]) -> list[TaskAgentEventRecord]:
    events = []
    for agent in agents:
        event = _stage_event_from_agent(agent)
        if event is not None:
            events.append(event)
    return events


def _stage_event_from_agent(agent: TaskAgentRecord) -> TaskAgentEventRecord | None:
    if agent.last_action_at is None and agent.status == WorkflowStageStatus.pending:
        return None
    return TaskAgentEventRecord(
        id=f"stage-{agent.id}-{agent.last_action_at.isoformat() if agent.last_action_at else 'pending'}",
        agent_id=agent.id,
        stage=agent.stage,
        kind="stage",
        status=agent.status.value,
        text=f"{agent.name}（{agent.role}）{_stage_status_label(agent.status)}：{agent.current_task}",
        time=agent.last_action_at,
        artifact_refs=agent.artifact_refs,
    )


def _human_request_events(requests: list[TaskHumanRequestRecord]) -> list[TaskAgentEventRecord]:
    return [_human_request_event(request) for request in requests]


def _human_request_event(request: TaskHumanRequestRecord) -> TaskAgentEventRecord:
    stage = normalize_workflow_stage(request.stage)
    request_status = human_request_status_value(request.status)
    title = _human_request_event_title(request, stage)
    return TaskAgentEventRecord(
        id=f"request-{request.id}",
        agent_id=stage.value,
        stage=stage,
        kind="human_request",
        status=request_status,
        text=f"人工确认 {title} 当前状态：{request_status}",
        time=request.updated_at or request.created_at,
        artifact_refs=_flatten_artifact_refs(request.payload.get("artifact_paths") if isinstance(request.payload, dict) else None),
    )


def _human_request_event_title(request: TaskHumanRequestRecord, stage: WorkflowStage) -> str:
    if isinstance(request.payload, dict):
        title = request.payload.get("title") or request.payload.get("request_type")
        if title:
            return str(title)
    return stage.value


def _sort_events(events: list[TaskAgentEventRecord]) -> list[TaskAgentEventRecord]:
    return sorted(events, key=lambda item: item.time.timestamp() if item.time else 0.0, reverse=True)[:20]


def _sort_messages(messages: list[TaskAgentMessageRecord]) -> list[TaskAgentMessageRecord]:
    return sorted(messages, key=lambda item: item.time.timestamp() if item.time else 0.0, reverse=True)[:80]
