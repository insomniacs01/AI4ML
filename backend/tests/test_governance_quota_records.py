from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.governance import TeamMemberRecord, TeamProfileRecord
from backend.app.services.governance_quota_records import (
    ConnectorSummary,
    coerce_non_negative_int,
    quota_map,
    quota_record_from_payload,
    quota_scope,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _profile(user_id: str, display_name: str) -> TeamProfileRecord:
    return TeamProfileRecord(user_id=user_id, email=f"{user_id}@example.test", display_name=display_name)


def _member(user_id: str, display_name: str) -> TeamMemberRecord:
    return TeamMemberRecord(
        team_id="team-1",
        user_id=user_id,
        role="admin",
        member_status="active",
        profile=_profile(user_id, display_name),
    )


def test_quota_scope_sets_owner_identity_for_member_and_connector_scopes() -> None:
    assert quota_scope("member", "user-1").user_id == "user-1"
    assert quota_scope("member", "user-1").connector_id is None
    assert quota_scope("connector", "connector-1").user_id is None
    assert quota_scope("connector", "connector-1").connector_id == "connector-1"
    assert quota_scope("team", "team-1").user_id is None
    assert quota_scope("team", "team-1").connector_id is None


def test_quota_map_uses_scope_key_with_identity_fallbacks() -> None:
    rows = quota_map(
        [
            {"scope_type": "member", "user_id": "user-1", "token_quota": 100},
            {"scope_type": "connector", "connector_id": "connector-1", "token_quota": 200},
            {"scope_type": "team", "scope_key": "team-1", "token_quota": 300},
            "invalid",
        ]
    )

    assert set(rows) == {("member", "user-1"), ("connector", "connector-1"), ("team", "team-1")}


def test_quota_record_from_member_payload_uses_member_identity_and_remaining_tokens() -> None:
    record = quota_record_from_payload(
        "team-1",
        {
            "token_quota": "100",
            "token_used": "40",
            "warning_threshold": "10",
            "updated_at": NOW,
        },
        member=_member("user-1", "Alice"),
    )

    assert record.scope_type == "member"
    assert record.scope_key == "user-1"
    assert record.user_id == "user-1"
    assert record.display_name == "Alice"
    assert record.token_remaining == 60
    assert record.status == "active"
    assert record.warning_threshold == 10
    assert record.updated_at == NOW


def test_quota_record_from_connector_payload_defaults_to_exhausted_when_limit_is_consumed() -> None:
    record = quota_record_from_payload(
        "team-1",
        {"token_quota": 5, "token_used": 9, "warning_threshold": "bad"},
        connector=ConnectorSummary(id="connector-1", display_name="Connector One"),
    )

    assert record.scope_type == "connector"
    assert record.scope_key == "connector-1"
    assert record.connector_id == "connector-1"
    assert record.connector_display_name == "Connector One"
    assert record.token_remaining == 0
    assert record.status == "exhausted"
    assert record.warning_threshold == 0


def test_quota_record_from_payload_preserves_payload_subject_for_unhandled_rows() -> None:
    record = quota_record_from_payload(
        "team-1",
        {
            "user_id": "user-payload",
            "connector_id": "connector-payload",
            "connector_display_name": "Connector Payload",
            "status": "frozen",
        },
    )

    assert record.scope_type == "team"
    assert record.scope_key == "user-payload"
    assert record.user_id == "user-payload"
    assert record.connector_id == "connector-payload"
    assert record.connector_display_name == "Connector Payload"
    assert record.status == "frozen"


def test_coerce_non_negative_int_rejects_invalid_and_negative_values() -> None:
    assert coerce_non_negative_int("12") == 12
    assert coerce_non_negative_int("-5") == 0
    assert coerce_non_negative_int("bad") == 0
