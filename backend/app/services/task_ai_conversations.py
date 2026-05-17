from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import (
    TaskAIConversationResponse,
    TaskInteractiveChatMessage,
    TaskRecord,
    TokenUsageReport,
)


def build_task_ai_conversations(task: TaskRecord) -> TaskAIConversationResponse:
    warnings: list[str] = []
    return TaskAIConversationResponse(
        task_id=task.id,
        task_name=task.name,
        warnings=warnings,
        interactive_messages=_collect_interactive_messages(task, warnings),
        items=[],
        internal_states=[],
    )


def _collect_interactive_messages(task: TaskRecord, warnings: list[str]) -> list[TaskInteractiveChatMessage]:
    analysis = task.structured_requirements if isinstance(task.structured_requirements, dict) else None
    if analysis is None:
        return []

    history = analysis.get("interactive_chat_history")
    if history is None:
        return []
    if not isinstance(history, list):
        warnings.append("Interactive chat history exists, but it is not stored as a list.")
        return []

    items: list[TaskInteractiveChatMessage] = []
    for index, raw_item in enumerate(history):
        if not isinstance(raw_item, dict):
            warnings.append(f"Interactive chat message #{index + 1} is not a JSON object.")
            continue

        role = raw_item.get("role")
        content = raw_item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            warnings.append(f"Interactive chat message #{index + 1} is missing a valid role/content pair.")
            continue

        origin = _coerce_origin(raw_item, role=role)
        status = raw_item.get("status")
        if status not in {"ok", "error"}:
            status = "ok"

        items.append(
            TaskInteractiveChatMessage(
                id=str(raw_item.get("id") or f"interactive_chat_{index + 1}"),
                role=role,
                origin=origin,
                content=content,
                status=status,
                model_name=_coerce_str(raw_item.get("model_name")),
                composed_prompt=_coerce_str(raw_item.get("composed_prompt")),
                token_usage=_coerce_token_usage(raw_item.get("token_usage")),
                created_at=_parse_datetime(raw_item.get("created_at")),
            )
        )

    items.sort(key=lambda item: item.created_at.timestamp() if item.created_at else 0.0)
    return items


def _coerce_origin(raw_item: dict[str, Any], *, role: str) -> str:
    origin = raw_item.get("origin")
    if origin in {"user", "ai_model", "local_runtime"}:
        return origin
    return "user" if role == "user" else "ai_model"


def _coerce_token_usage(value: object) -> TokenUsageReport | None:
    if not isinstance(value, dict):
        return None
    try:
        return TokenUsageReport.model_validate(value)
    except Exception:
        return None


def _coerce_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
