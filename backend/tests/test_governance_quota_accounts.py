from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.governance_quota_accounts import (
    read_existing_quota_account,
    upsert_quota_account,
)
from backend.app.services.governance_quota_records import quota_scope


class RequestRecorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


def test_read_existing_quota_account_returns_first_row_or_empty() -> None:
    request = RequestRecorder([[{"token_quota": 100}], []])

    first_row = read_existing_quota_account(
        request,
        "team-1",
        "&user_id=eq.user-1",
        access_token="token",
    )
    missing_row = read_existing_quota_account(
        request,
        "team-1",
        "&user_id=eq.missing",
        access_token="token",
    )

    assert first_row == {"token_quota": 100}
    assert missing_row == {}
    assert request.calls[0]["path"].endswith("&user_id=eq.user-1&limit=1")
    assert request.calls[1]["path"].endswith("&user_id=eq.missing&limit=1")


def test_upsert_quota_account_patches_existing_row_and_preserves_omitted_values() -> None:
    request = RequestRecorder(
        [
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "scope_type": "member",
                    "scope_key": "user-1",
                    "token_quota": 200,
                    "status": "frozen",
                    "warning_threshold": 25,
                }
            ]
        ]
    )

    row = upsert_quota_account(
        request,
        "team-1",
        quota_scope("member", "user-1"),
        token_quota=None,
        status=None,
        warning_threshold=None,
        existing_row={
            "token_quota": 200,
            "status": "frozen",
            "warning_threshold": 25,
        },
        update_filter="&user_id=eq.user-1",
        access_token="token",
        action="quota adjust",
    )

    assert request.calls[0] == {
        "path": "quota_accounts?team_id=eq.team-1&user_id=eq.user-1",
        "access_token": "token",
        "method": "PATCH",
        "body": {
            "team_id": "team-1",
            "user_id": "user-1",
            "connector_id": None,
            "scope_type": "member",
            "scope_key": "user-1",
            "token_quota": 200,
            "status": "frozen",
            "warning_threshold": 25,
        },
    }
    assert row["token_quota"] == 200


def test_upsert_quota_account_inserts_connector_scope_when_missing() -> None:
    request = RequestRecorder(
        [
            {
                "team_id": "team-1",
                "connector_id": "connector-1",
                "scope_type": "connector",
                "scope_key": "connector-1",
                "token_quota": 400,
                "status": "active",
                "warning_threshold": 50,
            }
        ]
    )

    row = upsert_quota_account(
        request,
        "team-1",
        quota_scope("connector", "connector-1"),
        token_quota=400,
        status=None,
        warning_threshold=50,
        existing_row={},
        update_filter="&scope_type=eq.connector&scope_key=eq.connector-1",
        access_token="token",
        action="quota scope adjust",
    )

    assert request.calls[0]["path"] == "quota_accounts"
    assert request.calls[0]["method"] == "POST"
    assert request.calls[0]["body"]["connector_id"] == "connector-1"
    assert request.calls[0]["body"]["scope_type"] == "connector"
    assert row["connector_id"] == "connector-1"


def test_upsert_quota_account_preserves_single_record_error() -> None:
    request = RequestRecorder([[]])

    with pytest.raises(
        ConnectionError,
        match="Unexpected Supabase response shape during quota adjust",
    ):
        upsert_quota_account(
            request,
            "team-1",
            quota_scope("member", "user-1"),
            token_quota=100,
            status=None,
            warning_threshold=None,
            existing_row={},
            update_filter="&user_id=eq.user-1",
            access_token="token",
            action="quota adjust",
        )
