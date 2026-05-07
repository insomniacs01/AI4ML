from __future__ import annotations

import hashlib
import json
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


AGENT_DEFINITIONS: dict[WorkflowStage, dict[str, Any]] = {
    WorkflowStage.requirement_analysis: {
        "name": "Agent-Alpha",
        "role": "需求解析",
        "short_role": "需求",
        "description": "理解业务目标，整理任务约束与输出要求。",
        "x": 10,
        "y": 45,
    },
    WorkflowStage.data_analysis: {
        "name": "Agent-Beta",
        "role": "数据分析",
        "short_role": "数据",
        "description": "检查 CSV 字段、目标列、缺失值与任务类型。",
        "x": 27,
        "y": 24,
    },
    WorkflowStage.feature_engineering: {
        "name": "Agent-Gamma",
        "role": "特征工程",
        "short_role": "特征",
        "description": "生成数据处理与训练前特征逻辑。",
        "x": 45,
        "y": 57,
    },
    WorkflowStage.model_selection: {
        "name": "Agent-Delta",
        "role": "模型选择",
        "short_role": "模型",
        "description": "选择 AutoGluon 候选模型并组织比较策略。",
        "x": 62,
        "y": 30,
    },
    WorkflowStage.training_validation: {
        "name": "Agent-Epsilon",
        "role": "训练验证",
        "short_role": "训练",
        "description": "执行训练、验证、错误修复和 leaderboard 落盘。",
        "x": 76,
        "y": 62,
    },
    WorkflowStage.report_generation: {
        "name": "Agent-Zeta",
        "role": "报告生成",
        "short_role": "报告",
        "description": "汇总指标、产物、报告快照和在线预测入口。",
        "x": 90,
        "y": 44,
    },
}

STATUS_LABELS = {
    WorkflowStageStatus.pending: "待命",
    WorkflowStageStatus.running: "执行中",
    WorkflowStageStatus.waiting_human: "等待人工",
    WorkflowStageStatus.completed: "已完成",
    WorkflowStageStatus.failed: "失败",
}

MESSAGE_TYPE_LABELS = {
    "coordination": "协作安排",
    "handoff": "阶段交接",
    "acknowledgement": "接收确认",
    "blocker": "阻塞通知",
    "human_review": "人工节点",
    "result": "结果广播",
}


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
        if str(request.status.value if hasattr(request.status, "value") else request.status) in {"pending", "open"}
    }

    agents: list[TaskAgentRecord] = []
    for stage in PRIMARY_WORKFLOW_STAGES:
        definition = AGENT_DEFINITIONS[stage]
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
    return TaskAgentCollaborationResponse(
        task=task,
        runtime_mode=runtime_mode,
        stages=stages,
        requests=requests,
        agents=agents,
        events=_build_events(agents, requests, agent_events=agent_events if agent_runs else None),
        messages=_sort_messages(agent_messages or []),
    )


def agent_runtime_spec_for_stage(stage: WorkflowStage | str) -> dict[str, Any]:
    normalized_stage = normalize_workflow_stage(stage)
    definition = AGENT_DEFINITIONS[normalized_stage]
    return {
        "agent_id": normalized_stage.value,
        "stage": normalized_stage,
        "name": definition["name"],
        "role": definition["role"],
        "short_role": definition["short_role"],
        "description": definition["description"],
        "x": definition["x"],
        "y": definition["y"],
    }


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


def _progress_for_status(status: WorkflowStageStatus) -> int:
    if status == WorkflowStageStatus.completed:
        return 100
    if status == WorkflowStageStatus.failed:
        return 100
    if status == WorkflowStageStatus.running:
        return 62
    if status == WorkflowStageStatus.waiting_human:
        return 48
    return 0


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


def _build_stage_message_specs(
    *,
    stage: WorkflowStage,
    stage_status: WorkflowStageStatus,
    summary: str,
    artifact_refs: list[str] | dict | None,
    log_excerpt: str | None,
) -> list[dict[str, Any]]:
    stage = normalize_workflow_stage(stage)
    sender = agent_runtime_spec_for_stage(stage)
    next_stage = _next_primary_stage(stage)
    receiver = agent_runtime_spec_for_stage(next_stage) if next_stage is not None else None
    flattened_artifacts = _flatten_artifact_refs(artifact_refs)
    artifact_count = len(flattened_artifacts)
    payload = {
        "source": "workflow_stage_transition",
        "stage": stage.value,
        "status": stage_status.value,
        "summary": summary,
        "artifact_count": artifact_count,
        "artifact_refs": flattened_artifacts,
        "log_excerpt": log_excerpt,
    }

    if stage_status == WorkflowStageStatus.running and receiver is not None:
        content = (
            f"{sender['name']} 正在执行“{sender['role']}”。"
            f"请 {receiver['name']} 预备接收本阶段输出；当前安排：{summary}"
        )
        return [_message_spec(sender, receiver, "coordination", content, payload)]

    if stage_status == WorkflowStageStatus.completed and receiver is not None:
        handoff = (
            f"{sender['name']} 已完成“{sender['role']}”，向 {receiver['name']} 交接：{summary}"
            f"{_artifact_suffix(artifact_count)}"
        )
        acknowledgement = (
            f"{receiver['name']} 已接收 {sender['name']} 的阶段结果，"
            f"后续将在“{receiver['role']}”中使用这些约束、指标和产物。"
        )
        return [
            _message_spec(sender, receiver, "handoff", handoff, payload),
            _message_spec(receiver, sender, "acknowledgement", acknowledgement, payload),
        ]

    if stage_status == WorkflowStageStatus.completed and receiver is None:
        content = f"{sender['name']} 已完成最终汇总：{summary}{_artifact_suffix(artifact_count)}"
        return [_message_spec(sender, None, "result", content, payload)]

    if stage_status == WorkflowStageStatus.failed:
        content = (
            f"{sender['name']} 在“{sender['role']}”遇到阻塞：{summary}"
            f"{' 下游阶段需等待修复或人工决策。' if receiver is not None else ''}"
        )
        return [_message_spec(sender, receiver, "blocker", content, payload)]

    if stage_status == WorkflowStageStatus.waiting_human:
        content = (
            f"{sender['name']} 暂停在人工协同节点：{summary}"
            f"{' 完成人工确认后再交接给 ' + str(receiver['name']) + '。' if receiver is not None else ''}"
        )
        return [_message_spec(sender, receiver, "human_review", content, payload)]

    return []


def _message_spec(
    sender: dict[str, Any],
    receiver: dict[str, Any] | None,
    message_type: str,
    content: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    receiver_id = str(receiver["agent_id"]) if receiver is not None else None
    correlation_base = {
        "from": str(sender["agent_id"]),
        "to": receiver_id,
        "message_type": message_type,
        "content": content,
        "payload": payload,
    }
    digest = hashlib.sha1(json.dumps(correlation_base, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {
        "from_agent_id": str(sender["agent_id"]),
        "to_agent_id": receiver_id,
        "message_type": message_type,
        "content": content,
        "payload": {
            **payload,
            "from_agent_name": sender["name"],
            "from_agent_role": sender["role"],
            "to_agent_name": receiver["name"] if receiver is not None else None,
            "to_agent_role": receiver["role"] if receiver is not None else None,
            "message_type_label": MESSAGE_TYPE_LABELS.get(message_type, message_type),
        },
        "correlation_id": f"agent-msg:{digest}",
    }


def _next_primary_stage(stage: WorkflowStage) -> WorkflowStage | None:
    try:
        index = PRIMARY_WORKFLOW_STAGES.index(stage)
    except ValueError:
        return None
    next_index = index + 1
    return PRIMARY_WORKFLOW_STAGES[next_index] if next_index < len(PRIMARY_WORKFLOW_STAGES) else None


def _artifact_suffix(count: int) -> str:
    return f" 已附带 {count} 个真实产物引用。" if count else ""


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
    events: list[TaskAgentEventRecord] = []
    if agent_events:
        events.extend(agent_events)
    else:
        for agent in agents:
            if agent.last_action_at is None and agent.status == WorkflowStageStatus.pending:
                continue
            events.append(
                TaskAgentEventRecord(
                    id=f"stage-{agent.id}-{agent.last_action_at.isoformat() if agent.last_action_at else 'pending'}",
                    agent_id=agent.id,
                    stage=agent.stage,
                    kind="stage",
                    status=agent.status.value,
                    text=f"{agent.name}（{agent.role}）{STATUS_LABELS.get(agent.status, agent.status.value)}：{agent.current_task}",
                    time=agent.last_action_at,
                    artifact_refs=agent.artifact_refs,
                )
            )

    for request in requests:
        stage = normalize_workflow_stage(request.stage)
        title = None
        if isinstance(request.payload, dict):
            title = request.payload.get("title") or request.payload.get("request_type")
        request_status = request.status.value if hasattr(request.status, "value") else str(request.status)
        events.append(
            TaskAgentEventRecord(
                id=f"request-{request.id}",
                agent_id=stage.value,
                stage=stage,
                kind="human_request",
                status=request_status,
                text=f"人工节点 {title or stage.value} 当前状态：{request_status}",
                time=request.updated_at or request.created_at,
                artifact_refs=_flatten_artifact_refs(request.payload.get("artifact_paths") if isinstance(request.payload, dict) else None),
            )
        )

    events.sort(key=lambda item: item.time.timestamp() if item.time else 0.0, reverse=True)
    return events[:20]


def _sort_messages(messages: list[TaskAgentMessageRecord]) -> list[TaskAgentMessageRecord]:
    return sorted(messages, key=lambda item: item.time.timestamp() if item.time else 0.0, reverse=True)[:80]


def _flatten_artifact_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        flattened: list[str] = []
        for key, item in value.items():
            if isinstance(item, list):
                flattened.extend(str(child) for child in item if child)
            elif item:
                flattened.append(f"{key}: {item}")
        return flattened
    return [str(value)]
