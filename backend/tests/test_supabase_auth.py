from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.security import HTTPAuthorizationCredentials

from backend.app.core.supabase_auth import SupabaseClient, require_team_access


def test_get_team_access_uses_membership_query_from_jwt_subject() -> None:
    calls: list[str] = []
    client = SupabaseClient(_settings())

    def request_json(url: str, access_token: str):
        calls.append(url)
        assert access_token == _token("user-1")
        assert "/auth/v1/user" not in url
        return [{
            "team_id": "team-1",
            "user_id": "user-1",
            "role": "member",
            "member_status": "active",
        }]

    client._request_json = request_json  # type: ignore[method-assign]

    user, membership = client.get_team_access(_token("user-1"), team_id="team-1")
    cached_user, cached_membership = client.get_team_access(_token("user-1"), team_id="team-1")

    assert user.id == "user-1"
    assert user.email == "user-1@example.test"
    assert membership is not None
    assert membership["role"] == "member"
    assert cached_user.id == "user-1"
    assert cached_membership == membership
    assert calls == [
        "https://example.supabase.co/rest/v1/team_members"
        "?select=team_id,user_id,role,member_status&team_id=eq.team-1&user_id=eq.user-1&limit=1"
    ]


def test_require_team_access_builds_context_from_fast_membership() -> None:
    class FakeClient:
        def get_team_access(self, access_token: str, *, team_id: str):
            assert access_token == "token"
            assert team_id == "team-1"
            return (
                SimpleNamespace(id="user-1", email="user-1@example.test", raw={}),
                {
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "role": "admin",
                    "member_status": "active",
                },
            )

    context = require_team_access(
        team_id="team-1",
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
        client=FakeClient(),
    )

    assert context.team_id == "team-1"
    assert context.role == "admin"
    assert context.user.id == "user-1"
    assert context.access_token == "token"


def test_get_team_access_reads_persisted_membership_cache(tmp_path: Path) -> None:
    token = _token("user-1")
    first_client = SupabaseClient(_settings(tmp_path))

    def request_json(url: str, access_token: str):
        return [{
            "team_id": "team-1",
            "user_id": "user-1",
            "role": "member",
            "member_status": "active",
        }]

    first_client._request_json = request_json  # type: ignore[method-assign]
    first_client.get_team_access(token, team_id="team-1")

    second_client = SupabaseClient(_settings(tmp_path))

    def fail_if_remote_requested(url: str, access_token: str):
        raise AssertionError(f"persisted membership cache should avoid remote auth request: {url}")

    second_client._request_json = fail_if_remote_requested  # type: ignore[method-assign]

    user, membership = second_client.get_team_access(token, team_id="team-1")

    assert user.id == "user-1"
    assert membership is not None
    assert membership["role"] == "member"


def _settings(repo_root: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        supabase_rest_url="https://example.supabase.co/rest/v1",
        supabase_auth_user_url="https://example.supabase.co/auth/v1/user",
        supabase_publishable_key="key",
        supabase_timeout_seconds=10,
        supabase_configured=True,
        repo_root=repo_root,
    )


def _token(user_id: str) -> str:
    header = _base64url({"alg": "none"})
    payload = _base64url({"sub": user_id, "email": f"{user_id}@example.test"})
    return f"{header}.{payload}.signature"


def _base64url(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
