from __future__ import annotations

from backend.app.models.task import (
    TaskAIConversationResponse,
    TaskInteractiveChatMessage,
    TaskRecord,
)
from backend.app.services.task_interactive_chat_history import (
    INTERACTIVE_CHAT_HISTORY_KEY,
    indexed_interactive_chat_message_id,
    load_interactive_chat_history,
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

    history = analysis.get(INTERACTIVE_CHAT_HISTORY_KEY)
    if history is None:
        return []
    return load_interactive_chat_history(
        history,
        missing_id=indexed_interactive_chat_message_id,
        warnings=warnings,
        sort_by_created_at=True,
    )
