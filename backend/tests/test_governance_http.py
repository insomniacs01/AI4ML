from __future__ import annotations

import io
import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from backend.app.core.config import Settings
from backend.app.services import governance_http
from backend.app.services.governance_http import GovernanceHttpClient, unwrap_single_record


class FakeResponse:
    def __init__(self, raw_body: str) -> None:
        self.raw_body = raw_body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.raw_body.encode("utf-8")


def _settings() -> Settings:
    return Settings(
        AI4ML_SUPABASE_URL="https://example.test",
        AI4ML_SUPABASE_PUBLISHABLE_KEY="anon-key",
    )


def test_governance_http_client_builds_supabase_json_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: int) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse('{"ok": true}')

    monkeypatch.setattr(governance_http, "urlopen", fake_urlopen)

    result = GovernanceHttpClient(_settings()).request_json(
        path="/profiles?select=*",
        access_token="token-1",
        method="POST",
        body={"display_name": "Alice"},
        prefer="resolution=merge-duplicates,return=representation",
    )

    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url == "https://example.test/rest/v1/profiles?select=*"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer token-1"
    assert request.get_header("Apikey") == "anon-key"
    assert request.get_header("Accept-profile") == "public"
    assert request.get_header("Content-profile") == "public"
    assert request.get_header("Prefer") == "resolution=merge-duplicates,return=representation"
    assert json.loads((request.data or b"").decode("utf-8")) == {"display_name": "Alice"}
    assert result == {"ok": True}


def test_governance_http_client_returns_none_for_non_json_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(governance_http, "urlopen", lambda request, timeout: FakeResponse('{"ignored": true}'))

    result = GovernanceHttpClient(_settings()).request_json(
        path="team_members?id=eq.member-1",
        access_token="token-1",
        method="DELETE",
        expect_json=False,
    )

    assert result is None


def test_governance_http_client_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(governance_http, "urlopen", lambda request, timeout: FakeResponse("not-json"))

    with pytest.raises(ConnectionError, match="not valid JSON"):
        GovernanceHttpClient(_settings()).request_json(path="profiles", access_token="token-1")


def test_governance_http_client_maps_supabase_permission_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Request, timeout: int) -> FakeResponse:
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(b"forbidden"),
        )

    monkeypatch.setattr(governance_http, "urlopen", fake_urlopen)

    with pytest.raises(PermissionError, match="team-governance"):
        GovernanceHttpClient(_settings()).request_json(path="profiles", access_token="token-1")


def test_governance_http_client_requires_supabase_configuration() -> None:
    settings = Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY="")

    with pytest.raises(RuntimeError, match="team-governance storage is not configured"):
        GovernanceHttpClient(settings).request_json(path="profiles", access_token="token-1")


def test_unwrap_single_record_accepts_dict_or_singleton_list() -> None:
    assert unwrap_single_record({"id": "row-1"}, "test") == {"id": "row-1"}
    assert unwrap_single_record([{"id": "row-1"}], "test") == {"id": "row-1"}

    with pytest.raises(ConnectionError, match="Unexpected Supabase response shape"):
        unwrap_single_record([], "test")
