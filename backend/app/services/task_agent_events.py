from __future__ import annotations

from backend.app.models.task import (
    TaskAgentEventRecord,
    TaskAgentRecord,
    TaskHumanRequestRecord,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_agent_artifacts import flatten_artifact_refs
from backend.app.services.task_agent_status import agent_status_label
from backend.app.services.task_human_request_status import human_request_status_value


def build_task_agent_events(
    agents: list[TaskAgentRecord],
    requests: list[TaskHumanRequestRecord],
    *,
    agent_events: list[TaskAgentEventRecord] | None = None,
) -> list[TaskAgentEventRecord]:
    events = list(agent_events) if agent_events else _stage_events_from_agents(agents)
    events.extend(_human_request_events(requests))
    return _sort_events(events)


def _sort_events(events: list[TaskAgentEventRecord]) -> list[TaskAgentEventRecord]:
    return sorted(events, key=lambda item: item.time.timestamp() if item.time else 0.0, reverse=True)[:20]


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
        text=f"{agent.name}（{agent.role}）{agent_status_label(agent.status)}：{agent.current_task}",
        time=agent.last_action_at,
        artifact_refs=agent.artifact_refs,
    )


def _human_request_events(requests: list[TaskHumanRequestRecord]) -> list[TaskAgentEventRecord]:
    return [_human_request_event(request) for request in requests]


def _human_request_event(request: TaskHumanRequestRecord) -> TaskAgentEventRecord:
    stage = normalize_workflow_stage(request.stage)
    request_status = human_request_status_value(request.status)
    title = _human_request_event_title(request, stage)
    payload = request.payload if isinstance(request.payload, dict) else None
    return TaskAgentEventRecord(
        id=f"request-{request.id}",
        agent_id=stage.value,
        stage=stage,
        kind="human_request",
        status=request_status,
        text=f"人工确认 {title} 当前状态：{request_status}",
        time=request.updated_at or request.created_at,
        artifact_refs=flatten_artifact_refs(payload.get("artifact_paths") if payload else None),
    )


def _human_request_event_title(request: TaskHumanRequestRecord, stage: WorkflowStage) -> str:
    if isinstance(request.payload, dict):
        title = request.payload.get("title") or request.payload.get("request_type")
        if title:
            return str(title)
    return stage.value
