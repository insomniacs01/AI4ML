from __future__ import annotations

from typing import Any

from backend.app.models.task import TokenUsageReport
from backend.app.services.task_token_ledger_writes import TOKEN_LEDGER_UPSERT_PATH
from backend.app.services.task_token_repository import TaskTokenRepository


class RequestRecorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request_json(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


def test_upsert_token_ledger_skips_missing_usage_without_side_effects() -> None:
    http = RequestRecorder([])
    repository = TaskTokenRepository(http)

    repository.upsert_token_ledger(
        team_id="team-1",
        task_id="task-1",
        phase="codex",
        source_key="workspace-1",
        usage=None,
        access_token="token",
        user_id="user-1",
    )

    assert http.calls == []


def test_upsert_token_ledger_adjusts_member_usage_by_delta_only() -> None:
    http = RequestRecorder([[{"id": "ledger-1", "total_tokens": 20}], [{"id": "ledger-1"}], None])
    repository = TaskTokenRepository(http)

    repository.upsert_token_ledger(
        team_id="team-1",
        task_id="task-1",
        phase="codex",
        source_key="workspace-1",
        usage=TokenUsageReport(input_tokens=18, output_tokens=9, total_tokens=27),
        access_token="token",
        user_id="user-1",
        connector_display_name="Codex model",
        stage_key="codex_native",
        calculation_method="codex_app_server_token_usage",
    )

    assert len(http.calls) == 3
    assert http.calls[0]["path"].endswith(
        "&team_id=eq.team-1&task_id=eq.task-1&phase=eq.codex&source_key=eq.workspace-1&limit=1"
    )
    assert http.calls[1]["path"] == TOKEN_LEDGER_UPSERT_PATH
    assert http.calls[1]["method"] == "POST"
    assert http.calls[1]["prefer"] == "resolution=merge-duplicates,return=representation"
    assert http.calls[1]["body"]["total_tokens"] == 27
    assert http.calls[1]["body"]["connector_display_name"] == "Codex model"
    assert http.calls[2] == {
        "path": "rpc/adjust_member_token_usage",
        "access_token": "token",
        "method": "POST",
        "body": {
            "target_team_id": "team-1",
            "target_user_id": "user-1",
            "token_delta": 7,
        },
        "expect_json": False,
    }


def test_upsert_token_ledger_does_not_adjust_member_usage_when_total_is_unchanged() -> None:
    http = RequestRecorder([[{"id": "ledger-1", "total_tokens": 27}], [{"id": "ledger-1"}]])
    repository = TaskTokenRepository(http)

    repository.upsert_token_ledger(
        team_id="team-1",
        task_id="task-1",
        phase="codex",
        source_key="workspace-1",
        usage=TokenUsageReport(input_tokens=18, output_tokens=9, total_tokens=27),
        access_token="token",
        user_id="user-1",
    )

    assert [call["path"] for call in http.calls] == [
        "token_ledgers?select=id,total_tokens&team_id=eq.team-1"
        "&task_id=eq.task-1&phase=eq.codex&source_key=eq.workspace-1&limit=1",
        TOKEN_LEDGER_UPSERT_PATH,
    ]
