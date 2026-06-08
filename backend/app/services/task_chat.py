from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.core.config import Settings
from backend.app.models.task import TaskInteractiveChatMessage, TaskRecord, TokenUsageReport
from backend.app.services.task_human_context import build_task_human_context_block
from backend.app.services.task_interactive_chat_history import (
    INTERACTIVE_CHAT_HISTORY_KEY,
    load_interactive_chat_history,
)
from backend.app.services.openai_compatible_provider import call_openai_compatible_provider
from backend.app.services.provider_availability import OpenAICompatibleProvider


MAX_HISTORY_MESSAGES = 12


@dataclass
class TaskChatResult:
    task: TaskRecord
    assistant_message: TaskInteractiveChatMessage
    token_usage: TokenUsageReport | None
    token_usage_calculation_method: str | None = None


def send_task_chat_message(task: TaskRecord, *, prompt: str, settings: Settings) -> TaskChatResult:
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("请输入要发给 AI 的 prompt。")

    structured_requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    history = load_interactive_chat_history(structured_requirements.get(INTERACTIVE_CHAT_HISTORY_KEY))

    user_message = TaskInteractiveChatMessage(
        id=f"chat_{uuid4().hex}",
        role="user",
        origin="user",
        content=normalized_prompt,
        created_at=datetime.now(timezone.utc),
    )
    history.append(user_message)

    composed_prompt = _build_chat_prompt(task, history)
    provider = OpenAICompatibleProvider(settings)
    reason = provider.unavailability_reason()
    if reason is not None:
        raise RuntimeError(f"当前 AI 连接器不可用：{reason}")

    provider_result = call_openai_compatible_provider(
        prompt=composed_prompt,
        settings=settings,
        system_message=(
            "You are the interactive AI collaborator inside AI4ML. "
            "Help the user discuss the task, data, prompt design, code ideas, and debugging steps. "
            "Do not claim to have executed code or changed task state unless the user has explicitly run those actions. "
            "Prefer answering in Chinese unless the user explicitly requests another language."
        ),
        temperature=0.2,
        max_tokens=1200,
    )
    if provider_result.token_usage is None:
        raise RuntimeError("AI Provider 响应中缺少 usage token 信息，无法记录本次对话消耗。")
    assistant_message = TaskInteractiveChatMessage(
        id=f"chat_{uuid4().hex}",
        role="assistant",
        origin="ai_model",
        content=provider_result.text,
        model_name=settings.ai_provider_model_name,
        composed_prompt=composed_prompt,
        token_usage=provider_result.token_usage,
        created_at=datetime.now(timezone.utc),
    )
    token_usage = provider_result.token_usage

    history.append(assistant_message)
    structured_requirements[INTERACTIVE_CHAT_HISTORY_KEY] = [message.model_dump(mode="json") for message in history]
    task.structured_requirements = structured_requirements

    return TaskChatResult(
        task=task,
        assistant_message=assistant_message,
        token_usage=token_usage,
        token_usage_calculation_method=provider_result.token_usage_calculation_method,
    )


def _build_chat_prompt(task: TaskRecord, history: list[TaskInteractiveChatMessage]) -> str:
    recent_history = history[-MAX_HISTORY_MESSAGES:]
    history_lines = []
    for message in recent_history:
        speaker = "User" if message.role == "user" else "Assistant"
        history_lines.append(f"{speaker}: {_clip_text(message.content, 2500)}")

    return (
        "You are continuing an interactive AI discussion for an AI4ML task.\n"
        "Use the task context and recent conversation below to answer the latest user prompt directly and concretely.\n"
        "If the user asks for a prompt, code idea, model suggestion, or debugging step, provide it explicitly.\n"
        "If task context is missing, say what is missing instead of inventing details.\n\n"
        f"{_build_task_context(task)}\n\n"
        "Recent conversation:\n"
        f"{chr(10).join(history_lines) if history_lines else 'No previous conversation.'}\n"
    )


def _build_task_context(task: TaskRecord) -> str:
    analysis = _task_analysis(task)
    metric_name = _analysis_str(analysis, "metric_name")
    reasoning = _analysis_str(analysis, "reasoning")

    return (
        "Task context:\n"
        f"- Task name: {task.name}\n"
        f"- Task description: {_clip_text(task.description, 1500)}\n"
        f"- Dataset filename: {task.dataset_filename or 'N/A'}\n"
        f"- Label column: {task.label_column or 'N/A'}\n"
        f"- Problem type: {task.problem_type or 'N/A'}\n"
        f"- Suggested metric: {metric_name or 'N/A'}\n"
        f"- Task status: {_task_status_text(task)}\n"
        f"- Latest notes: {_clip_text(task.notes or 'N/A', 800)}\n"
        f"- Latest run output dir: {_latest_run_output_dir(task) or 'N/A'}\n"
        f"- CSV columns: {_column_names_text(analysis)}\n"
        f"- Analysis reasoning: {_clip_text(reasoning or 'N/A', 1200)}\n"
        f"- Preview rows: {_preview_rows_text(analysis)}\n"
        f"- Human collaboration decisions:\n{build_task_human_context_block(task)}\n"
    )


def _task_analysis(task: TaskRecord) -> dict[object, object]:
    return task.structured_requirements if isinstance(task.structured_requirements, dict) else {}


def _analysis_str(analysis: dict[object, object], key: str) -> str | None:
    value = analysis.get(key)
    return value if isinstance(value, str) else None


def _task_status_text(task: TaskRecord) -> str:
    return task.status.value if hasattr(task.status, "value") else str(task.status)


def _latest_run_output_dir(task: TaskRecord) -> str | None:
    if task.last_run_attempt and task.last_run_attempt.output_dir:
        return task.last_run_attempt.output_dir
    if task.last_run and task.last_run.output_dir:
        return task.last_run.output_dir
    return None


def _column_names_text(analysis: dict[object, object]) -> str:
    column_names = analysis.get("column_names")
    if not isinstance(column_names, list) or not column_names:
        return "N/A"
    return json.dumps(column_names, ensure_ascii=False)


def _preview_rows_text(analysis: dict[object, object]) -> str:
    preview_rows = analysis.get("preview_rows")
    if not isinstance(preview_rows, list):
        return "N/A"
    return json.dumps(preview_rows[:3], ensure_ascii=False, indent=2)


def _clip_text(value: str, limit: int) -> str:
    normalized = value.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."
