from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.governance_team_profiles import list_team_profiles, update_team_profile


class RequestRecorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


def test_list_team_profiles_sorts_deduplicates_and_projects_rows() -> None:
    request = RequestRecorder(
        [
            [
                {"user_id": "user-b", "email": "b@example.test", "display_name": "Bob"},
                {"user_id": "user-a", "email": "", "display_name": None},
                {"email": "missing-id@example.test"},
                "ignored",
            ]
        ]
    )

    profiles = list_team_profiles(request, ["user-b", "", "user-a", "user-b"], access_token="token")

    assert request.calls == [
        {
            "path": 'profiles?select=user_id,email,display_name&user_id=in.("user-a","user-b")',
            "access_token": "token",
        }
    ]
    assert [profile.user_id for profile in profiles] == ["user-b", "user-a"]
    assert profiles[0].email == "b@example.test"
    assert profiles[1].email is None
    assert profiles[1].display_name is None


def test_list_team_profiles_returns_empty_without_request_when_ids_are_empty() -> None:
    request = RequestRecorder([])

    assert list_team_profiles(request, ["", ""], access_token="token") == []
    assert request.calls == []


def test_list_team_profiles_rejects_unexpected_response() -> None:
    request = RequestRecorder([{"unexpected": "shape"}])

    with pytest.raises(ConnectionError, match="Unexpected profile response"):
        list_team_profiles(request, ["user-1"], access_token="token")


def test_update_team_profile_trims_display_name_and_projects_record() -> None:
    request = RequestRecorder([{"user_id": "user-1", "email": "", "display_name": "Alice"}])

    profile = update_team_profile(request, "user-1", display_name=" Alice ", access_token="token")

    assert request.calls == [
        {
            "path": "profiles?user_id=eq.user-1",
            "access_token": "token",
            "method": "PATCH",
            "body": {"display_name": "Alice"},
        }
    ]
    assert profile.user_id == "user-1"
    assert profile.email is None
    assert profile.display_name == "Alice"


def test_update_team_profile_sends_null_display_name_for_empty_input() -> None:
    request = RequestRecorder([{"user_id": "user-1", "email": "user-1@example.test", "display_name": None}])

    profile = update_team_profile(request, "user-1", display_name="", access_token="token")

    assert request.calls[0]["body"] == {"display_name": None}
    assert profile.email == "user-1@example.test"
    assert profile.display_name is None
