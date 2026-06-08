from __future__ import annotations

from typing import Any
from urllib.parse import quote

from backend.app.models.task import TokenUsageReport


TOKEN_LEDGER_UPSERT_PATH = "token_ledgers?on_conflict=team_id,task_id,phase,source_key"


def token_ledger_lookup_path(team_id: str, task_id: str, phase: str, source_key: str) -> str:
    return (
        "token_ledgers"
        f"?select=id,total_tokens&team_id=eq.{quote(team_id, safe='')}"
        f"&task_id=eq.{quote(task_id, safe='')}"
        f"&phase=eq.{quote(phase, safe='')}"
        f"&source_key=eq.{quote(source_key, safe='')}"
        "&limit=1"
    )


def previous_ledger_total(existing: Any) -> int:
    if isinstance(existing, list) and existing:
        first_row = existing[0]
        if isinstance(first_row, dict):
            return coerce_non_negative_int(first_row.get("total_tokens"))
    return 0


def token_usage_delta(usage: TokenUsageReport, previous_total: int) -> int:
    return usage.total_tokens - previous_total


def build_token_ledger_payload(
    *,
    team_id: str,
    task_id: str,
    phase: str,
    source_key: str,
    usage: TokenUsageReport,
    user_id: str | None,
    connector_id: str | None,
    connector_display_name: str | None,
    model_name: str | None,
    stage_key: str | None,
    calculation_method: str | None,
) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "task_id": task_id,
        "user_id": user_id,
        "connector_id": connector_id,
        "connector_display_name": connector_display_name,
        "phase": phase,
        "stage_key": stage_key,
        "source_key": source_key,
        "model_name": model_name,
        "calculation_method": calculation_method,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "raw_usage": usage.model_dump(),
    }


def coerce_non_negative_int(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return max(result, 0)
