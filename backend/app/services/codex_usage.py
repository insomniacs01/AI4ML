from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.models.task import TokenUsageReport
from backend.app.services.codex_common import coerce_non_negative_int, read_json


def read_codex_token_usage(workspace_path: str | None) -> TokenUsageReport | None:
    if not workspace_path:
        return None
    return token_usage_from_payload(read_json(Path(workspace_path) / "output" / "token_usage.json"))


def token_usage_from_artifacts(artifacts: dict[str, Any]) -> TokenUsageReport | None:
    return token_usage_from_payload(artifacts.get("token_usage"))


def token_usage_from_payload(payload: Any) -> TokenUsageReport | None:
    if not isinstance(payload, dict):
        return None

    total = payload.get("total") if isinstance(payload.get("total"), dict) else {}
    input_tokens = coerce_non_negative_int(total.get("total_input_tokens", total.get("input_tokens")))
    output_tokens = coerce_non_negative_int(total.get("total_output_tokens", total.get("output_tokens")))
    total_tokens = coerce_non_negative_int(total.get("total_tokens")) or input_tokens + output_tokens
    if total_tokens <= 0:
        return None

    return TokenUsageReport(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        sessions=_normalize_usage_collection(payload.get("sessions"), "session_name"),
        conversations=_normalize_usage_collection(payload.get("conversations"), "conversation_id"),
    )


def _normalize_usage_collection(payload: Any, name_key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    items: list[dict[str, Any]] = []
    for name, usage in payload.items():
        if not isinstance(usage, dict):
            continue
        items.append(
            {
                name_key: str(name),
                "input_tokens": coerce_non_negative_int(usage.get("input_tokens")),
                "output_tokens": coerce_non_negative_int(usage.get("output_tokens")),
                "total_tokens": coerce_non_negative_int(usage.get("total_tokens")),
            }
        )
    return sorted(items, key=lambda item: item["total_tokens"], reverse=True)
