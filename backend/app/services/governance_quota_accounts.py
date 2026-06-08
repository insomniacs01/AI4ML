from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.services.governance_http import unwrap_single_record
from backend.app.services.governance_quota_records import QuotaScope
from backend.app.services.governance_quota_writes import build_quota_account_payload
from backend.app.services.governance_usage_queries import quota_existing_path, quota_update_path

RequestJson = Callable[..., Any]


def read_existing_quota_account(
    request_json: RequestJson,
    team_id: str,
    filter_path: str,
    *,
    access_token: str,
) -> dict[str, Any]:
    existing = request_json(
        path=quota_existing_path(team_id, filter_path),
        access_token=access_token,
    )
    return existing[0] if isinstance(existing, list) and existing else {}


def upsert_quota_account(
    request_json: RequestJson,
    team_id: str,
    scope: QuotaScope,
    *,
    token_quota: int | None,
    status: str | None,
    warning_threshold: int | None,
    existing_row: dict[str, Any],
    update_filter: str,
    access_token: str,
    action: str,
) -> dict[str, Any]:
    payload = build_quota_account_payload(
        team_id,
        scope,
        token_quota=token_quota,
        status=status,
        warning_threshold=warning_threshold,
        existing_row=existing_row,
    )
    if existing_row:
        updated = request_json(
            path=quota_update_path(team_id, update_filter),
            access_token=access_token,
            method="PATCH",
            body=payload,
        )
    else:
        updated = request_json(
            path="quota_accounts",
            access_token=access_token,
            method="POST",
            body=payload,
        )
    return unwrap_single_record(updated, action)
