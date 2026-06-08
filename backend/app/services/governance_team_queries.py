from __future__ import annotations

from urllib.parse import quote


TEAM_MEMBER_SELECT = "team_id,user_id,role,member_status,invited_by,joined_at,updated_at"
TEAM_SELECT = "id,name,invite_code,created_by,description,status,created_at,updated_at"
PROFILE_SELECT = "user_id,email,display_name"


def team_members_path(team_id: str) -> str:
    return (
        "team_members"
        f"?select={TEAM_MEMBER_SELECT}&team_id=eq.{quote(team_id, safe='')}"
        "&order=joined_at.asc"
    )


def team_path(team_id: str) -> str:
    return (
        "teams"
        f"?select={TEAM_SELECT}&id=eq.{quote(team_id, safe='')}&limit=1"
    )


def team_update_path(team_id: str) -> str:
    return f"teams?id=eq.{quote(team_id, safe='')}"


def team_member_update_path(team_id: str, user_id: str) -> str:
    return (
        "team_members"
        f"?team_id=eq.{quote(team_id, safe='')}"
        f"&user_id=eq.{quote(user_id, safe='')}"
    )


def profile_update_path(user_id: str) -> str:
    return f"profiles?user_id=eq.{quote(user_id, safe='')}"


def normalized_profile_ids(user_ids: list[str]) -> list[str]:
    return sorted({item for item in user_ids if item})


def profiles_path(user_ids: list[str]) -> str:
    normalized_ids = normalized_profile_ids(user_ids)
    in_list = ",".join(f'"{item}"' for item in normalized_ids)
    quoted_in_list = quote(in_list, safe='(),"')
    return f"profiles?select={PROFILE_SELECT}&user_id=in.({quoted_in_list})"
