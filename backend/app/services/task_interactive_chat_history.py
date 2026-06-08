from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.models.task import TaskInteractiveChatMessage, TokenUsageReport


INTERACTIVE_CHAT_HISTORY_KEY = "interactive_chat_history"
logger = logging.getLogger(__name__)


def random_interactive_chat_message_id(_: int) -> str:
    return f"chat_{uuid4().hex}"


def indexed_interactive_chat_message_id(index: int) -> str:
    return f"interactive_chat_{index + 1}"


def load_interactive_chat_history(
    raw_history: object,
    *,
    missing_id: Callable[[int], str] = random_interactive_chat_message_id,
    warnings: list[str] | None = None,
    sort_by_created_at: bool = False,
) -> list[TaskInteractiveChatMessage]:
    if not isinstance(raw_history, list):
        if raw_history is not None and warnings is not None:
            warnings.append("Interactive chat history exists, but it is not stored as a list.")
        return []

    messages: list[TaskInteractiveChatMessage] = []
    for index, item in enumerate(raw_history):
        message = _chat_message_from_history_item(item, missing_id=missing_id(index))
        if message is None:
            if warnings is not None:
                warnings.append(_invalid_history_item_warning(index, item))
            continue
        messages.append(message)

    if sort_by_created_at:
        messages.sort(key=_chat_message_sort_key)
    return messages


def _chat_message_from_history_item(item: object, *, missing_id: str) -> TaskInteractiveChatMessage | None:
    if not isinstance(item, dict):
        return None
    role = item.get("role")
    content = _chat_content(item.get("content"))
    if role not in {"user", "assistant"} or content is None:
        return None

    return TaskInteractiveChatMessage(
        id=str(item.get("id") or missing_id),
        role=role,
        origin=_chat_origin(item.get("origin"), role),
        content=content,
        status=_chat_status(item.get("status")),
        model_name=_optional_chat_str(item.get("model_name")),
        composed_prompt=_optional_chat_str(item.get("composed_prompt")),
        token_usage=_chat_token_usage(item.get("token_usage")),
        created_at=_chat_created_at(item.get("created_at")),
    )


def _invalid_history_item_warning(index: int, item: object) -> str:
    if not isinstance(item, dict):
        return f"Interactive chat message #{index + 1} is not a JSON object."
    return f"Interactive chat message #{index + 1} is missing a valid role/content pair."


def _chat_content(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _chat_origin(value: object, role: object) -> str:
    if value in {"user", "ai_model", "local_runtime"}:
        return str(value)
    return "user" if role == "user" else "ai_model"


def _chat_status(value: object) -> str:
    return str(value) if value in {"ok", "error"} else "ok"


def _optional_chat_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _chat_token_usage(value: object) -> TokenUsageReport | None:
    if not isinstance(value, dict):
        return None
    try:
        return TokenUsageReport.model_validate(value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not parse interactive chat token usage: %s", exc)
        return None


def _chat_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _chat_message_sort_key(message: TaskInteractiveChatMessage) -> float:
    if message.created_at is None:
        return 0.0
    return message.created_at.timestamp()
