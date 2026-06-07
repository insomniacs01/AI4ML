from __future__ import annotations

from typing import Any

from backend.app.models.governance import TeamProfileRecord, TokenLedgerRecord
from backend.app.services.governance_payload_values import coerce_non_negative_int, optional_payload_str


def normalize_ledger_limit(limit: int) -> int:
    return min(max(limit, 1), 1000)


def token_ledger_from_payload(
    payload: dict[str, Any],
    *,
    profile_map: dict[str, TeamProfileRecord],
    task_map: dict[str, str],
    connector_map: dict[str, str],
) -> TokenLedgerRecord:
    ledger_user_id = optional_payload_str(payload.get("user_id"))
    profile = profile_map.get(ledger_user_id or "")
    ledger_task_id = optional_payload_str(payload.get("task_id"))
    ledger_connector_id = optional_payload_str(payload.get("connector_id"))
    connector_display_name = optional_payload_str(payload.get("connector_display_name")) or connector_map.get(
        ledger_connector_id or ""
    )
    return TokenLedgerRecord(
        id=str(payload.get("id")),
        team_id=str(payload.get("team_id")),
        user_id=ledger_user_id,
        user_display_name=profile.display_name if profile else None,
        user_email=profile.email if profile else None,
        task_id=ledger_task_id,
        task_name=task_map.get(ledger_task_id or ""),
        connector_id=ledger_connector_id,
        connector_display_name=connector_display_name,
        phase=str(payload.get("phase")),
        stage_key=optional_payload_str(payload.get("stage_key")),
        source_key=str(payload.get("source_key")),
        model_name=optional_payload_str(payload.get("model_name")),
        input_tokens=coerce_non_negative_int(payload.get("input_tokens")),
        output_tokens=coerce_non_negative_int(payload.get("output_tokens")),
        total_tokens=coerce_non_negative_int(payload.get("total_tokens")),
        calculation_method=optional_payload_str(payload.get("calculation_method")),
        raw_usage=payload.get("raw_usage") if isinstance(payload.get("raw_usage"), dict) else None,
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
    )
