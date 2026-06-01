from __future__ import annotations

import re
from typing import Any

from backend.app.models.task import (
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)


_RAW_RUNTIME_FALLBACK = "系统已隐藏原始运行日志；请查看诊断结论或报错文件。"
_RAW_RUNTIME_MARKERS = (
    "return code:",
    "traceback (most recent call last)",
    "logs.txt tail",
    "info_logs.txt tail",
    "detail_logs.txt tail",
    "debugging_logs.txt",
    "captured stdout tail",
    "captured stderr",
    "http request: post",
    "using openai model",
    "wire_api=chat_completions",
    "tutorial retrieval is disabled",
    "install faiss-cpu",
)


def sanitize_stage_record(record: WorkflowStageRecord) -> WorkflowStageRecord:
    data = record.model_dump()
    data["summary"] = _sanitize_runtime_text(data.get("summary"), fallback=_fallback_for_stage(record.stage, record.status))
    data["log_excerpt"] = _sanitize_runtime_text(data.get("log_excerpt"), fallback=None)
    return WorkflowStageRecord.model_validate(data)


def sanitize_agent_record(record: TaskAgentRecord) -> TaskAgentRecord:
    data = record.model_dump()
    data["current_task"] = _sanitize_runtime_text(
        data.get("current_task"),
        fallback=_fallback_for_stage(record.stage, record.status),
    )
    data["log_excerpt"] = _sanitize_runtime_text(data.get("log_excerpt"), fallback=None)
    return TaskAgentRecord.model_validate(data)


def sanitize_agent_events(events: list[TaskAgentEventRecord]) -> list[TaskAgentEventRecord]:
    sanitized: list[TaskAgentEventRecord] = []
    for event in events:
        data = event.model_dump()
        data["text"] = _sanitize_runtime_text(data.get("text"), fallback=_fallback_for_stage(event.stage, event.status))
        sanitized.append(TaskAgentEventRecord.model_validate(data))
    return sanitized


def sanitize_agent_messages(messages: list[TaskAgentMessageRecord]) -> list[TaskAgentMessageRecord]:
    sanitized: list[TaskAgentMessageRecord] = []
    for message in messages:
        data = message.model_dump()
        data["content"] = _sanitize_runtime_text(data.get("content"), fallback=_RAW_RUNTIME_FALLBACK)
        payload = data.get("payload")
        if isinstance(payload, dict):
            payload = dict(payload)
            for key in ("summary", "log_excerpt"):
                if key in payload:
                    payload[key] = _sanitize_runtime_text(payload.get(key), fallback=None)
            data["payload"] = payload
        sanitized.append(TaskAgentMessageRecord.model_validate(data))
    return sanitized


def _sanitize_runtime_text(value: Any, *, fallback: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    if _looks_like_raw_runtime_text(text):
        return fallback
    return text


def _looks_like_raw_runtime_text(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in _RAW_RUNTIME_MARKERS):
        return True
    if re.search(r"[a-z]:\\[^ ]{10,}", lowered):
        return True
    if len(value) > 420 and any(marker in lowered for marker in ("info ", "brief ", "warning ")):
        return True
    return False


def _fallback_for_stage(stage: WorkflowStage | str | None, status: WorkflowStageStatus | str | None) -> str:
    try:
        normalized_stage = normalize_workflow_stage(stage) if stage is not None else None
    except ValueError:
        normalized_stage = None
    raw_status = status.value if hasattr(status, "value") else str(status or "")
    if raw_status == WorkflowStageStatus.failed.value:
        if normalized_stage == WorkflowStage.report_generation:
            return "训练验证失败，报告暂未生成。"
        if normalized_stage == WorkflowStage.training_validation:
            return "训练或验证失败，系统已保留报错文件并等待诊断。"
        return "当前阶段失败，系统已保留报错文件并等待诊断。"
    if raw_status == WorkflowStageStatus.running.value:
        return "当前阶段正在运行，等待系统更新状态。"
    if raw_status == WorkflowStageStatus.completed.value:
        return "当前阶段已完成。"
    if raw_status == WorkflowStageStatus.waiting_human.value:
        return "当前阶段等待人工协同处理。"
    return _RAW_RUNTIME_FALLBACK
