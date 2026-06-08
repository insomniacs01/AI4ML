from __future__ import annotations

from backend.app.services.governance_usage_queries import (
    QUOTA_SELECT,
    connector_names_path,
    member_quota_filter,
    quota_accounts_path,
    quota_existing_path,
    quota_update_path,
    scope_quota_filter,
    token_ledgers_path,
)


def test_quota_paths_quote_team_and_filters() -> None:
    filter_path = member_quota_filter("user/1")

    assert quota_accounts_path("team/1") == f"quota_accounts?select={QUOTA_SELECT}&team_id=eq.team%2F1"
    assert filter_path == "&user_id=eq.user%2F1"
    assert quota_existing_path("team/1", filter_path) == (
        f"quota_accounts?select={QUOTA_SELECT}&team_id=eq.team%2F1&user_id=eq.user%2F1&limit=1"
    )
    assert quota_update_path("team/1", filter_path) == "quota_accounts?team_id=eq.team%2F1&user_id=eq.user%2F1"


def test_scope_filter_quotes_scope_parts() -> None:
    assert scope_quota_filter("connector", "connector/1") == "&scope_type=eq.connector&scope_key=eq.connector%2F1"


def test_token_ledgers_path_clamps_limit_and_appends_optional_filters() -> None:
    assert token_ledgers_path("team/1", limit=5000, user_id="user 1", task_id="task/1") == (
        "token_ledgers?select=*&team_id=eq.team%2F1&order=created_at.desc&limit=1000"
        "&user_id=eq.user%201&task_id=eq.task%2F1"
    )


def test_connector_names_path_quotes_team() -> None:
    assert connector_names_path("team/1") == "ai_connectors?select=id,display_name&team_id=eq.team%2F1"
