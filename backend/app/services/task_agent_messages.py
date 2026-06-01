from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.app.models.task import WorkflowStage, WorkflowStageStatus, normalize_workflow_stage
from backend.app.services.task_agent_artifacts import flatten_artifact_refs
from backend.app.services.task_agent_definitions import (
    MESSAGE_TYPE_LABELS,
    agent_runtime_spec_for_stage,
    next_primary_stage,
)


def build_stage_message_specs(
    *,
    stage: WorkflowStage,
    stage_status: WorkflowStageStatus,
    summary: str,
    artifact_refs: list[str] | dict | None,
    log_excerpt: str | None,
) -> list[dict[str, Any]]:
    stage = normalize_workflow_stage(stage)
    sender = agent_runtime_spec_for_stage(stage)
    next_stage = next_primary_stage(stage)
    receiver = agent_runtime_spec_for_stage(next_stage) if next_stage is not None else None
    flattened_artifacts = flatten_artifact_refs(artifact_refs)
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
            f"后续将在“{receiver['role']}”中使用这些约束、指标和生成文件。"
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
            f"{sender['name']} 暂停在人工确认：{summary}"
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


def _artifact_suffix(count: int) -> str:
    return f" 已附带 {count} 个真实文件引用。" if count else ""
