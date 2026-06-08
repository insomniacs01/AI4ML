from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.app.models.governance import TeamProfileRecord
from backend.app.services.governance_token_ledger_listing import list_token_ledger_records


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RequestRecorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


class ProfileLookup:
    def __init__(self, profiles: list[TeamProfileRecord]) -> None:
        self.profiles = {profile.user_id: profile for profile in profiles}
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, user_ids: list[str], *, access_token: str) -> list[TeamProfileRecord]:
        self.calls.append((user_ids, access_token))
        return [self.profiles[user_id] for user_id in user_ids if user_id in self.profiles]


def _profile(user_id: str, display_name: str) -> TeamProfileRecord:
    return TeamProfileRecord(user_id=user_id, email=f"{user_id}@example.test", display_name=display_name)


def test_list_token_ledger_records_enriches_related_names_and_skips_non_dict_rows() -> None:
    request = RequestRecorder(
        [
            [
                {
                    "id": "ledger-1",
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "task_id": "task-1",
                    "connector_id": "connector-1",
                    "phase": "codex",
                    "source_key": "workspace",
                    "input_tokens": 5,
                    "output_tokens": 7,
                    "total_tokens": 12,
                    "created_at": NOW,
                    "updated_at": NOW,
                },
                "ignore",
            ],
            [{"id": "task-1", "name": "Task One"}],
            [{"id": "connector-1", "display_name": "Connector One"}],
        ]
    )
    profiles = ProfileLookup([_profile("user-1", "Alice")])

    records = list_token_ledger_records(
        request,
        profiles,
        "team-1",
        access_token="token",
        limit=5000,
        user_id="user-1",
        task_id="task-1",
    )

    assert len(records) == 1
    assert records[0].user_display_name == "Alice"
    assert records[0].task_name == "Task One"
    assert records[0].connector_display_name == "Connector One"
    assert records[0].total_tokens == 12
    assert "limit=1000" in request.calls[0]["path"]
    assert "&user_id=eq.user-1" in request.calls[0]["path"]
    assert "&task_id=eq.task-1" in request.calls[0]["path"]
    assert request.calls[1]["path"] == 'ai_tasks?select=id,name&team_id=eq.team-1&id=in.("task-1")'
    assert request.calls[2]["path"] == 'ai_connectors?select=id,display_name&team_id=eq.team-1&id=in.("connector-1")'
    assert profiles.calls == [(["user-1"], "token")]


def test_list_token_ledger_records_rejects_unexpected_response() -> None:
    request = RequestRecorder([{"unexpected": "shape"}])
    profiles = ProfileLookup([])

    with pytest.raises(ConnectionError, match="Unexpected token-ledgers response"):
        list_token_ledger_records(request, profiles, "team-1", access_token="token")

    assert profiles.calls == []
