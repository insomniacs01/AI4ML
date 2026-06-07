from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.governance import TeamProfileRecord
from backend.app.services.governance_token_ledgers import normalize_ledger_limit, token_ledger_from_payload


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _profile(user_id: str, display_name: str) -> TeamProfileRecord:
    return TeamProfileRecord(user_id=user_id, email=f"{user_id}@example.test", display_name=display_name)


def test_normalize_ledger_limit_clamps_to_supported_range() -> None:
    assert normalize_ledger_limit(-10) == 1
    assert normalize_ledger_limit(0) == 1
    assert normalize_ledger_limit(500) == 500
    assert normalize_ledger_limit(5000) == 1000


def test_token_ledger_from_payload_enriches_profile_task_and_connector_names() -> None:
    ledger = token_ledger_from_payload(
        {
            "id": "ledger-1",
            "team_id": "team-1",
            "user_id": "user-1",
            "task_id": "task-1",
            "connector_id": "connector-1",
            "phase": "codex",
            "stage_key": "codex_native",
            "source_key": "workspace-1",
            "model_name": "codex-model",
            "input_tokens": "12",
            "output_tokens": "8",
            "total_tokens": "20",
            "calculation_method": "artifact",
            "raw_usage": {"total_tokens": 20},
            "created_at": NOW,
            "updated_at": NOW,
        },
        profile_map={"user-1": _profile("user-1", "Alice")},
        task_map={"task-1": "Task One"},
        connector_map={"connector-1": "Connector One"},
    )

    assert ledger.user_display_name == "Alice"
    assert ledger.user_email == "user-1@example.test"
    assert ledger.task_name == "Task One"
    assert ledger.connector_display_name == "Connector One"
    assert ledger.input_tokens == 12
    assert ledger.output_tokens == 8
    assert ledger.total_tokens == 20
    assert ledger.raw_usage == {"total_tokens": 20}


def test_token_ledger_payload_connector_name_overrides_lookup_and_invalid_tokens_are_zero() -> None:
    ledger = token_ledger_from_payload(
        {
            "id": "ledger-1",
            "team_id": "team-1",
            "connector_id": "connector-1",
            "connector_display_name": "Payload Connector",
            "phase": "codex",
            "source_key": "workspace-1",
            "input_tokens": "bad",
            "output_tokens": -5,
            "total_tokens": None,
            "raw_usage": "not-a-dict",
            "created_at": NOW,
            "updated_at": NOW,
        },
        profile_map={},
        task_map={},
        connector_map={"connector-1": "Lookup Connector"},
    )

    assert ledger.connector_display_name == "Payload Connector"
    assert ledger.input_tokens == 0
    assert ledger.output_tokens == 0
    assert ledger.total_tokens == 0
    assert ledger.raw_usage is None
    assert ledger.user_id is None
    assert ledger.task_id is None
