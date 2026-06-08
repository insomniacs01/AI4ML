from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.models.governance import TeamMemberRecord, TeamProfileRecord
from backend.app.services.governance_http import unwrap_single_record
from backend.app.services.governance_team_queries import team_member_update_path
from backend.app.services.governance_team_records import team_member_from_payload

RequestJson = Callable[..., Any]
ListProfiles = Callable[..., list[TeamProfileRecord]]

TEAM_MEMBER_UPDATE_POLICY_ERROR = (
    "Supabase team_members update did not return a row. "
    "Apply the latest team_members update policy from supabase/schema.sql."
)


def update_team_member_role(
    request_json: RequestJson,
    list_profiles: ListProfiles,
    team_id: str,
    user_id: str,
    role: str,
    *,
    access_token: str,
) -> TeamMemberRecord:
    return _update_team_member(
        request_json,
        list_profiles,
        team_id,
        user_id,
        body={"role": role},
        action="team member role update",
        access_token=access_token,
        default_role=role,
    )


def update_team_member_status(
    request_json: RequestJson,
    list_profiles: ListProfiles,
    team_id: str,
    user_id: str,
    member_status: str,
    *,
    access_token: str,
) -> TeamMemberRecord:
    return _update_team_member(
        request_json,
        list_profiles,
        team_id,
        user_id,
        body={"member_status": member_status},
        action="team member status update",
        access_token=access_token,
        default_role="business_user",
        default_status=member_status,
    )


def _update_team_member(
    request_json: RequestJson,
    list_profiles: ListProfiles,
    team_id: str,
    user_id: str,
    *,
    body: dict[str, Any],
    action: str,
    access_token: str,
    default_role: str,
    default_status: str = "active",
) -> TeamMemberRecord:
    payload = request_json(
        path=team_member_update_path(team_id, user_id),
        access_token=access_token,
        method="PATCH",
        body=body,
    )
    try:
        updated = unwrap_single_record(payload, action)
    except ConnectionError as exc:
        raise RuntimeError(TEAM_MEMBER_UPDATE_POLICY_ERROR) from exc
    profiles = list_profiles([user_id], access_token=access_token)
    profile = profiles[0] if profiles else None
    return team_member_from_payload(
        updated,
        profile=profile,
        default_role=default_role,
        default_status=default_status,
    )
