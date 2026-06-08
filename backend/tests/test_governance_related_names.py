from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.governance_related_names import list_connector_names, list_task_names


class RequestRecorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


def test_list_task_names_deduplicates_sorts_and_falls_back_to_id() -> None:
    request = RequestRecorder(
        [[{"id": "task-b", "name": ""}, {"id": "task-a", "name": "Task A"}]]
    )

    names = list_task_names(request, "team-1", ["task-b", "", "task-a", "task-a"], access_token="token")

    assert names == {"task-a": "Task A", "task-b": "task-b"}
    assert request.calls == [
        {
            "path": 'ai_tasks?select=id,name&team_id=eq.team-1&id=in.("task-a","task-b")',
            "access_token": "token",
        }
    ]


def test_list_connector_names_skips_request_for_empty_ids() -> None:
    request = RequestRecorder([])

    assert list_connector_names(request, "team-1", [], access_token="token") == {}
    assert request.calls == []


def test_list_connector_names_rejects_unexpected_payload_shape() -> None:
    request = RequestRecorder([{"id": "connector-1"}])

    with pytest.raises(ConnectionError, match="Unexpected connector-name response"):
        list_connector_names(request, "team-1", ["connector-1"], access_token="token")
