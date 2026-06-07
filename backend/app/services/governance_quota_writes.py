from __future__ import annotations

from typing import Any

from backend.app.services.governance_payload_values import coerce_non_negative_int
from backend.app.services.governance_quota_records import QuotaScope


def build_quota_account_payload(
    team_id: str,
    scope: QuotaScope,
    *,
    token_quota: int | None,
    status: str | None,
    warning_threshold: int | None,
    existing_row: dict[str, Any],
) -> dict[str, Any]:
    resolved_token_quota = (
        token_quota
        if token_quota is not None
        else coerce_non_negative_int(existing_row.get("token_quota"))
    )
    return {
        "team_id": team_id,
        "user_id": scope.user_id,
        "connector_id": scope.connector_id,
        "scope_type": scope.scope_type,
        "scope_key": scope.scope_key,
        "token_quota": resolved_token_quota,
        "status": resolved_quota_status(
            status=status,
            token_quota=token_quota,
            resolved_token_quota=resolved_token_quota,
            existing_row=existing_row,
        ),
        "warning_threshold": (
            warning_threshold
            if warning_threshold is not None
            else coerce_non_negative_int(existing_row.get("warning_threshold"))
        ),
    }


def resolved_quota_status(
    *,
    status: str | None,
    token_quota: int | None,
    resolved_token_quota: int,
    existing_row: dict[str, Any],
) -> str:
    resolved_status = status or str(existing_row.get("status") or "active")
    if (
        status is None
        and token_quota is not None
        and resolved_status == "exhausted"
        and resolved_token_quota > coerce_non_negative_int(existing_row.get("token_used"))
    ):
        return "active"
    return resolved_status
