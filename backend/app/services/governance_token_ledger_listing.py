from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.models.governance import TeamProfileRecord, TokenLedgerRecord
from backend.app.services.governance_related_names import list_connector_names, list_task_names
from backend.app.services.governance_token_ledgers import token_ledger_from_payload
from backend.app.services.governance_usage_queries import token_ledgers_path

RequestJson = Callable[..., Any]
ListProfiles = Callable[..., list[TeamProfileRecord]]


def list_token_ledger_records(
    request_json: RequestJson,
    list_profiles: ListProfiles,
    team_id: str,
    *,
    access_token: str,
    limit: int = 500,
    user_id: str | None = None,
    task_id: str | None = None,
) -> list[TokenLedgerRecord]:
    payload = request_json(
        path=token_ledgers_path(team_id, limit=limit, user_id=user_id, task_id=task_id),
        access_token=access_token,
    )
    if not isinstance(payload, list):
        raise ConnectionError("Unexpected token-ledgers response from Supabase.")

    return build_token_ledger_records(
        payload,
        request_json=request_json,
        list_profiles=list_profiles,
        team_id=team_id,
        access_token=access_token,
    )


def build_token_ledger_records(
    payload: list[Any],
    *,
    request_json: RequestJson,
    list_profiles: ListProfiles,
    team_id: str,
    access_token: str,
) -> list[TokenLedgerRecord]:
    profile_map = {
        item.user_id: item
        for item in list_profiles(
            _payload_ids(payload, "user_id"),
            access_token=access_token,
        )
    }
    task_map = list_task_names(
        request_json,
        team_id,
        _payload_ids(payload, "task_id"),
        access_token=access_token,
    )
    connector_map = list_connector_names(
        request_json,
        team_id,
        _payload_ids(payload, "connector_id"),
        access_token=access_token,
    )

    return [
        token_ledger_from_payload(
            item,
            profile_map=profile_map,
            task_map=task_map,
            connector_map=connector_map,
        )
        for item in payload
        if isinstance(item, dict)
    ]


def _payload_ids(payload: list[Any], key: str) -> list[str]:
    return [
        str(item.get(key))
        for item in payload
        if isinstance(item, dict) and item.get(key)
    ]
