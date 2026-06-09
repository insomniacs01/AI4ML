from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.app.models.governance import TeamSettingsUpdateRequest
from backend.app.services.governance_team import GovernanceTeamRepository


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


def _repository(responses: list[Any]) -> tuple[GovernanceTeamRepository, RequestRecorder]:
    request = RequestRecorder(responses)
    return GovernanceTeamRepository(request_json=request), request


def test_list_members_fetches_profiles_and_projects_member_records() -> None:
    repository, request = _repository(
        [
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "role": "developer_user",
                    "member_status": "active",
                    "invited_by": "owner-1",
                    "joined_at": NOW,
                },
                "not-a-row",
            ],
            [{"user_id": "user-1", "email": "user-1@example.test", "display_name": "Alice"}],
        ]
    )

    members = repository.list_members("team-1", access_token="token")

    assert len(members) == 1
    assert members[0].user_id == "user-1"
    assert members[0].role == "developer_user"
    assert members[0].joined_at == NOW
    assert members[0].profile is not None
    assert members[0].profile.display_name == "Alice"
    assert request.calls[0]["path"].startswith("team_members?select=")
    assert request.calls[0]["path"].endswith("&team_id=eq.team-1&order=joined_at.asc")
    assert request.calls[1]["path"] == 'profiles?select=user_id,email,display_name&user_id=in.("user-1")'


def test_list_members_uses_cache_until_member_update() -> None:
    repository, request = _repository(
        [
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "role": "member",
                    "member_status": "active",
                }
            ],
            [{"user_id": "user-1", "email": "user-1@example.test", "display_name": "Alice"}],
            {
                "team_id": "team-1",
                "user_id": "user-1",
                "role": "admin",
                "member_status": "active",
            },
            [{"user_id": "user-1", "email": "user-1@example.test", "display_name": "Alice"}],
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "role": "admin",
                    "member_status": "active",
                }
            ],
            [{"user_id": "user-1", "email": "user-1@example.test", "display_name": "Alice"}],
        ]
    )

    first = repository.list_members("team-1", access_token="token")
    second = repository.list_members("team-1", access_token="token")

    assert first[0].role == "member"
    assert second[0].role == "member"
    assert len(request.calls) == 2

    repository.update_member_role("team-1", "user-1", "admin", access_token="token")
    refreshed = repository.list_members("team-1", access_token="token")

    assert refreshed[0].role == "admin"
    assert [call["path"].split("?")[0] for call in request.calls] == [
        "team_members",
        "profiles",
        "team_members",
        "profiles",
        "team_members",
        "profiles",
    ]


def test_get_team_settings_uses_cache_and_returns_copies() -> None:
    repository, request = _repository(
        [
            [
                {
                    "id": "team-1",
                    "name": "Team One",
                    "invite_code": "INVITE",
                    "created_by": "owner-1",
                    "description": "Original",
                    "status": "active",
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            [
                {
                    "team_id": "team-1",
                    "user_id": "owner-1",
                    "role": "team_owner",
                    "member_status": "active",
                }
            ],
            [{"user_id": "owner-1", "email": "owner-1@example.test", "display_name": "Owner One"}],
        ]
    )

    first = repository.get_team_settings("team-1", access_token="token")
    assert first is not None
    first.name = "Mutated"
    second = repository.get_team_settings("team-1", access_token="token")

    assert second is not None
    assert second.name == "Team One"
    assert len(request.calls) == 3


def test_update_team_settings_sends_trimmed_patch_and_returns_owner_enriched_record() -> None:
    repository, request = _repository(
        [
            [
                {
                    "id": "team-1",
                    "name": "Team One",
                    "invite_code": "INVITE",
                    "created_by": "creator-1",
                    "description": None,
                    "status": "active",
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            [
                {
                    "team_id": "team-1",
                    "user_id": "owner-1",
                    "role": "team_owner",
                    "member_status": "active",
                }
            ],
            [{"user_id": "owner-1", "email": "owner-1@example.test", "display_name": "Owner One"}],
        ]
    )

    settings = repository.update_team_settings(
        "team-1",
        TeamSettingsUpdateRequest(name=" Team One ", description="   ", status="active"),
        access_token="token",
    )

    assert request.calls[0]["method"] == "PATCH"
    assert request.calls[0]["path"] == "teams?id=eq.team-1"
    assert request.calls[0]["body"] == {
        "name": "Team One",
        "description": None,
        "status": "active",
    }
    assert settings.owner_user_id == "owner-1"
    assert settings.owner_display_name == "Owner One"


def test_update_member_role_preserves_runtime_error_for_empty_supabase_update_response() -> None:
    repository, _ = _repository([[]])

    with pytest.raises(RuntimeError, match="team_members update did not return a row"):
        repository.update_member_role("team-1", "user-1", "admin", access_token="token")


def test_update_profile_preserves_profile_projection_defaults() -> None:
    repository, request = _repository(
        [
            {
                "user_id": "user-1",
                "email": "",
                "display_name": "Alice",
            }
        ]
    )

    profile = repository.update_profile("user-1", display_name=" Alice ", access_token="token")

    assert request.calls[0]["method"] == "PATCH"
    assert request.calls[0]["path"] == "profiles?user_id=eq.user-1"
    assert request.calls[0]["body"] == {"display_name": "Alice"}
    assert profile.user_id == "user-1"
    assert profile.email is None
    assert profile.display_name == "Alice"
