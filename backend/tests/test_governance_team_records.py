from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.governance import TeamMemberRecord, TeamProfileRecord
from backend.app.services.governance_team_records import (
    profile_records_from_payload,
    team_member_from_payload,
    team_settings_from_payload,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _profile(user_id: str, display_name: str) -> TeamProfileRecord:
    return TeamProfileRecord(
        user_id=user_id,
        email=f"{user_id}@example.test",
        display_name=display_name,
    )


def _member(
    user_id: str,
    *,
    role: str = "member",
    member_status: str = "active",
    profile: TeamProfileRecord | None = None,
) -> TeamMemberRecord:
    return TeamMemberRecord(
        team_id="team-1",
        user_id=user_id,
        role=role,
        member_status=member_status,
        profile=profile,
    )


def test_profile_records_from_payload_filters_invalid_rows() -> None:
    records = profile_records_from_payload(
        [
            {"user_id": "user-1", "email": "user-1@example.test", "display_name": "Alice"},
            {"email": "missing-id@example.test"},
            "not-a-row",
        ]
    )

    assert len(records) == 1
    assert records[0].user_id == "user-1"
    assert records[0].email == "user-1@example.test"
    assert records[0].display_name == "Alice"


def test_team_member_from_payload_applies_defaults_and_profile() -> None:
    profile = _profile("user-1", "Alice")

    record = team_member_from_payload(
        {
            "team_id": "team-1",
            "user_id": "user-1",
            "invited_by": "owner-1",
            "joined_at": NOW,
        },
        profile=profile,
        default_role="developer_user",
        default_status="frozen",
    )

    assert record.team_id == "team-1"
    assert record.user_id == "user-1"
    assert record.role == "developer_user"
    assert record.member_status == "frozen"
    assert record.invited_by == "owner-1"
    assert record.joined_at == NOW
    assert record.profile == profile


def test_team_settings_from_payload_prefers_active_owner_profile() -> None:
    owner_profile = _profile("owner-1", "Owner One")

    settings = team_settings_from_payload(
        {
            "id": "team-1",
            "name": "Team One",
            "invite_code": "INVITE",
            "created_by": "creator-1",
            "description": "desc",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
        },
        [
            _member("owner-1", role="team_owner", profile=owner_profile),
            _member("owner-2", role="team_owner", member_status="frozen", profile=_profile("owner-2", "Owner Two")),
        ],
    )

    assert settings.owner_user_id == "owner-1"
    assert settings.owner_display_name == "Owner One"
    assert settings.owner_email == "owner-1@example.test"
    assert settings.created_by == "creator-1"
    assert settings.description == "desc"
    assert settings.created_at == NOW
    assert settings.updated_at == NOW


def test_team_settings_from_payload_falls_back_to_creator_without_active_owner() -> None:
    settings = team_settings_from_payload(
        {
            "id": "team-1",
            "name": None,
            "invite_code": None,
            "created_by": "creator-1",
            "description": "",
            "status": None,
        },
        [_member("owner-1", role="team_owner", member_status="removed")],
    )

    assert settings.name == ""
    assert settings.invite_code == ""
    assert settings.owner_user_id == "creator-1"
    assert settings.owner_display_name is None
    assert settings.owner_email is None
    assert settings.description is None
    assert settings.status == "active"
