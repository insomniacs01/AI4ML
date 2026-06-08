from __future__ import annotations

from backend.app.models.task import TokenUsageReport
from backend.app.services.task_token_ledger_writes import (
    build_token_ledger_payload,
    coerce_non_negative_int,
    previous_ledger_total,
    token_ledger_lookup_path,
    token_usage_delta,
)


def test_token_ledger_lookup_path_quotes_conflict_keys() -> None:
    assert token_ledger_lookup_path("team/1", "task 1", "phase/a", "source+b") == (
        "token_ledgers?select=id,total_tokens&team_id=eq.team%2F1"
        "&task_id=eq.task%201&phase=eq.phase%2Fa&source_key=eq.source%2Bb&limit=1"
    )


def test_previous_ledger_total_coerces_existing_total() -> None:
    assert previous_ledger_total([{"total_tokens": "42"}]) == 42
    assert previous_ledger_total([{"total_tokens": -5}]) == 0
    assert previous_ledger_total([{"total_tokens": "bad"}]) == 0
    assert previous_ledger_total([]) == 0
    assert previous_ledger_total({"total_tokens": 12}) == 0
    assert coerce_non_negative_int(None) == 0


def test_build_token_ledger_payload_projects_usage_and_metadata() -> None:
    usage = TokenUsageReport(input_tokens=10, output_tokens=5, total_tokens=15)

    payload = build_token_ledger_payload(
        team_id="team-1",
        task_id="task-1",
        phase="codex",
        source_key="workspace-1",
        usage=usage,
        user_id="user-1",
        connector_id="connector-1",
        connector_display_name="Connector One",
        model_name="model-a",
        stage_key="codex_native",
        calculation_method="codex_app_server_token_usage",
    )

    raw_usage = payload.pop("raw_usage")
    assert payload == {
        "team_id": "team-1",
        "task_id": "task-1",
        "user_id": "user-1",
        "connector_id": "connector-1",
        "connector_display_name": "Connector One",
        "phase": "codex",
        "stage_key": "codex_native",
        "source_key": "workspace-1",
        "model_name": "model-a",
        "calculation_method": "codex_app_server_token_usage",
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert raw_usage["input_tokens"] == 10
    assert raw_usage["output_tokens"] == 5
    assert raw_usage["total_tokens"] == 15
    assert token_usage_delta(usage, previous_total=8) == 7
