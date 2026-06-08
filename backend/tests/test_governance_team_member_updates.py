from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.app.models.governance import TeamProfileRecord
from backend.app.services.governance_team_member_updates import (
    TEAM_MEMBER_UPDATE_POLICY_ERROR,
    update_team_member_role,
    update_team_member_status,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RequestRecorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


class ProfileLookup:
    def __init__(self, profiles: list[TeamProfileRecord]) -> None:
        self.profiles = {profile.user_id: profile for profile in profiles}
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, user_ids: list[str], *, access_token: str) -> list[TeamProfileRecord]:
        self.calls.append((user_ids, access_token))
        return [self.profiles[user_id] for user_id in user_ids if user_id in self.profiles]


def _profile(user_id: str, display_name: str) -> TeamProfileRecord:
    return TeamProfileRecord(user_id=user_id, email=f"{user_id}@example.test", display_name=display_name)


def test_update_team_member_role_patches_role_and_enriches_profile() -> None:
    request = RequestRecorder(
        [
            {
                "team_id": "team-1",
                "user_id": "user-1",
                "member_status": "active",
                "joined_at": NOW,
            }
        ]
    )
    profiles = ProfileLookup([_profile("user-1", "Alice")])

    member = update_team_member_role(
        request,
        profiles,
        "team-1",
        "user-1",
        "admin",
        access_token="token",
    )

    assert request.calls == [
        {
            "path": "team_members?team_id=eq.team-1&user_id=eq.user-1",
            "access_token": "token",
            "method": "PATCH",
            "body": {"role": "admin"},
        }
    ]
    assert profiles.calls == [(["user-1"], "token")]
    assert member.role == "admin"
    assert member.member_status == "active"
    assert member.profile is not None
    assert member.profile.display_name == "Alice"


def test_update_team_member_status_patches_status_with_business_user_default_role() -> None:
    request = RequestRecorder(
        [
            {
                "team_id": "team-1",
                "user_id": "user-2",
            }
        ]
    )
    profiles = ProfileLookup([])

    member = update_team_member_status(
        request,
        profiles,
        "team-1",
        "user-2",
        "frozen",
        access_token="token",
    )

    assert request.calls[0]["body"] == {"member_status": "frozen"}
    assert member.role == "business_user"
    assert member.member_status == "frozen"
    assert member.profile is None


def test_update_team_member_raises_runtime_error_for_empty_update_response() -> None:
    request = RequestRecorder([[]])
    profiles = ProfileLookup([])

    with pytest.raises(RuntimeError, match="team_members update did not return a row"):
        update_team_member_role(request, profiles, "team-1", "user-1", "admin", access_token="token")

    assert profiles.calls == []
    assert TEAM_MEMBER_UPDATE_POLICY_ERROR.startswith("Supabase team_members update did not return a row")
