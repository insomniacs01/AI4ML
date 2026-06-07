from __future__ import annotations

from typing import Any

from backend.app.models.governance import TeamMemberRecord, TeamProfileRecord, TeamSettingsRecord
from backend.app.services.governance_payload_values import optional_payload_str


def profile_record_from_payload(payload: dict[str, Any]) -> TeamProfileRecord | None:
    if not payload.get("user_id"):
        return None
    return TeamProfileRecord(
        user_id=str(payload.get("user_id")),
        email=optional_payload_str(payload.get("email")),
        display_name=optional_payload_str(payload.get("display_name")),
    )


def profile_records_from_payload(payload: list[Any]) -> list[TeamProfileRecord]:
    records: list[TeamProfileRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        record = profile_record_from_payload(item)
        if record is not None:
            records.append(record)
    return records


def team_member_from_payload(
    payload: dict[str, Any],
    *,
    profile: TeamProfileRecord | None = None,
    default_role: str = "member",
    default_status: str = "active",
) -> TeamMemberRecord:
    return TeamMemberRecord(
        team_id=str(payload.get("team_id")),
        user_id=str(payload.get("user_id")),
        role=str(payload.get("role", default_role)),
        member_status=str(payload.get("member_status", default_status)),
        invited_by=optional_payload_str(payload.get("invited_by")),
        joined_at=payload.get("joined_at"),
        profile=profile,
    )


def team_settings_from_payload(
    payload: dict[str, Any],
    members: list[TeamMemberRecord],
) -> TeamSettingsRecord:
    owner = next((item for item in members if item.role == "team_owner" and item.member_status == "active"), None)
    owner_user_id = owner.user_id if owner is not None else optional_payload_str(payload.get("created_by"))
    owner_profile = owner.profile if owner is not None else None
    return TeamSettingsRecord(
        id=str(payload.get("id")),
        name=str(payload.get("name") or ""),
        invite_code=str(payload.get("invite_code") or ""),
        created_by=str(payload.get("created_by") or owner_user_id or ""),
        owner_user_id=owner_user_id,
        owner_display_name=owner_profile.display_name if owner_profile else None,
        owner_email=owner_profile.email if owner_profile else None,
        description=optional_payload_str(payload.get("description")),
        status=str(payload.get("status") or "active"),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
    )
