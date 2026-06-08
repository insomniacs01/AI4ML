from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_ai_conversations import build_task_ai_conversations


def _task(structured_requirements: object) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-ai-conversations",
        team_id="team-1",
        created_by="user-1",
        name="AI conversations",
        description="Inspect interactive chat history.",
        status=TaskStatus.running,
        structured_requirements=structured_requirements,
        created_at=now,
        updated_at=now,
    )


def test_task_ai_conversations_loads_sorted_interactive_chat_history() -> None:
    response = build_task_ai_conversations(
        _task(
            {
                "interactive_chat_history": [
                    {
                        "role": "assistant",
                        "origin": "unexpected",
                        "status": "unexpected",
                        "content": " later ",
                        "created_at": "2026-01-02T00:00:00Z",
                    },
                    {
                        "id": "message-1",
                        "role": "user",
                        "origin": "user",
                        "status": "ok",
                        "content": " earlier ",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                ]
            }
        )
    )

    assert response.warnings == []
    assert [message.content for message in response.interactive_messages] == ["earlier", "later"]
    assert response.interactive_messages[0].id == "message-1"
    assert response.interactive_messages[1].id == "interactive_chat_1"
    assert response.interactive_messages[1].origin == "ai_model"
    assert response.interactive_messages[1].status == "ok"


def test_task_ai_conversations_reports_invalid_history_shape() -> None:
    response = build_task_ai_conversations(
        _task(
            {
                "interactive_chat_history": [
                    "invalid",
                    {"role": "system", "content": "ignored"},
                    {"role": "user", "content": "ok"},
                ]
            }
        )
    )

    assert [message.content for message in response.interactive_messages] == ["ok"]
    assert response.warnings == [
        "Interactive chat message #1 is not a JSON object.",
        "Interactive chat message #2 is missing a valid role/content pair.",
    ]


def test_task_ai_conversations_warns_when_history_is_not_a_list() -> None:
    response = build_task_ai_conversations(_task({"interactive_chat_history": {"role": "user", "content": "hello"}}))

    assert response.interactive_messages == []
    assert response.warnings == ["Interactive chat history exists, but it is not stored as a list."]
