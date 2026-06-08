from __future__ import annotations

from urllib.parse import quote

from backend.app.services.governance_token_ledgers import normalize_ledger_limit


QUOTA_SELECT = (
    "team_id,user_id,connector_id,scope_type,scope_key,token_quota,"
    "token_used,status,warning_threshold,updated_at"
)


def quota_accounts_path(team_id: str) -> str:
    return (
        "quota_accounts"
        f"?select={QUOTA_SELECT}&team_id=eq.{quote(team_id, safe='')}"
    )


def quota_existing_path(team_id: str, filter_path: str) -> str:
    return (
        "quota_accounts"
        f"?select={QUOTA_SELECT}&team_id=eq.{quote(team_id, safe='')}"
        f"{filter_path}&limit=1"
    )


def quota_update_path(team_id: str, update_filter: str) -> str:
    return (
        "quota_accounts"
        f"?team_id=eq.{quote(team_id, safe='')}{update_filter}"
    )


def member_quota_filter(user_id: str) -> str:
    return f"&user_id=eq.{quote(user_id, safe='')}"


def scope_quota_filter(scope_type: str, scope_key: str) -> str:
    return (
        f"&scope_type=eq.{quote(scope_type, safe='')}"
        f"&scope_key=eq.{quote(scope_key, safe='')}"
    )


def token_ledgers_path(
    team_id: str,
    *,
    limit: int,
    user_id: str | None = None,
    task_id: str | None = None,
) -> str:
    path = (
        "token_ledgers"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&order=created_at.desc&limit={normalize_ledger_limit(limit)}"
    )
    if user_id:
        path += f"&user_id=eq.{quote(user_id, safe='')}"
    if task_id:
        path += f"&task_id=eq.{quote(task_id, safe='')}"
    return path


def connector_names_path(team_id: str) -> str:
    return (
        "ai_connectors"
        f"?select=id,display_name&team_id=eq.{quote(team_id, safe='')}"
    )
