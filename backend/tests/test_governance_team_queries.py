from __future__ import annotations

from backend.app.services.governance_team_queries import (
    PROFILE_SELECT,
    TEAM_MEMBER_SELECT,
    TEAM_SELECT,
    normalized_profile_ids,
    profile_update_path,
    profiles_path,
    team_member_update_path,
    team_members_path,
    team_path,
    team_update_path,
)


def test_team_query_paths_quote_identifiers() -> None:
    assert team_members_path("team/1") == (
        f"team_members?select={TEAM_MEMBER_SELECT}&team_id=eq.team%2F1&order=joined_at.asc"
    )
    assert team_path("team/1") == f"teams?select={TEAM_SELECT}&id=eq.team%2F1&limit=1"
    assert team_update_path("team/1") == "teams?id=eq.team%2F1"


def test_member_and_profile_update_paths_quote_identifiers() -> None:
    assert team_member_update_path("team/1", "user 1") == "team_members?team_id=eq.team%2F1&user_id=eq.user%201"
    assert profile_update_path("user 1") == "profiles?user_id=eq.user%201"


def test_profiles_path_sorts_deduplicates_and_quotes_ids() -> None:
    assert normalized_profile_ids(["user/b", "", "user a", "user/b"]) == ["user a", "user/b"]
    assert profiles_path(["user/b", "", "user a", "user/b"]) == (
        f'profiles?select={PROFILE_SELECT}&user_id=in.("user%20a","user%2Fb")'
    )
