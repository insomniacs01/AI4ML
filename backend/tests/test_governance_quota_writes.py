from backend.app.services.governance_quota_records import quota_scope
from backend.app.services.governance_quota_writes import build_quota_account_payload, resolved_quota_status


def test_build_quota_account_payload_preserves_existing_values_when_inputs_are_omitted() -> None:
    payload = build_quota_account_payload(
        "team-1",
        quota_scope("member", "user-1"),
        token_quota=None,
        status=None,
        warning_threshold=None,
        existing_row={"token_quota": 200, "status": "frozen", "warning_threshold": 25},
    )

    assert payload == {
        "team_id": "team-1",
        "user_id": "user-1",
        "connector_id": None,
        "scope_type": "member",
        "scope_key": "user-1",
        "token_quota": 200,
        "status": "frozen",
        "warning_threshold": 25,
    }


def test_build_quota_account_payload_writes_connector_identity_for_connector_scope() -> None:
    payload = build_quota_account_payload(
        "team-1",
        quota_scope("connector", "connector-1"),
        token_quota=400,
        status="active",
        warning_threshold=50,
        existing_row={},
    )

    assert payload["user_id"] is None
    assert payload["connector_id"] == "connector-1"
    assert payload["scope_type"] == "connector"
    assert payload["scope_key"] == "connector-1"
    assert payload["token_quota"] == 400
    assert payload["warning_threshold"] == 50


def test_resolved_quota_status_reactivates_exhausted_quota_when_limit_increases() -> None:
    status = resolved_quota_status(
        status=None,
        token_quota=200,
        resolved_token_quota=200,
        existing_row={"status": "exhausted", "token_used": 100},
    )

    assert status == "active"


def test_resolved_quota_status_preserves_explicit_status_and_non_increased_exhaustion() -> None:
    assert (
        resolved_quota_status(
            status="frozen",
            token_quota=200,
            resolved_token_quota=200,
            existing_row={"status": "exhausted", "token_used": 100},
        )
        == "frozen"
    )
    assert (
        resolved_quota_status(
            status=None,
            token_quota=100,
            resolved_token_quota=100,
            existing_row={"status": "exhausted", "token_used": 100},
        )
        == "exhausted"
    )
