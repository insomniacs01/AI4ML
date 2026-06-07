from __future__ import annotations

from backend.app.models.governance import TeamMemberRecord, TeamProfileRecord
from backend.app.services.governance_quota_listing import build_quota_records


def _profile(user_id: str, display_name: str) -> TeamProfileRecord:
    return TeamProfileRecord(user_id=user_id, email=f"{user_id}@example.test", display_name=display_name)


def _member(user_id: str, display_name: str) -> TeamMemberRecord:
    return TeamMemberRecord(
        team_id="team-1",
        user_id=user_id,
        role="member",
        member_status="active",
        profile=_profile(user_id, display_name),
    )


def test_build_quota_records_orders_members_connectors_team_and_unhandled_rows() -> None:
    records = build_quota_records(
        "team-1",
        members=[_member("user-1", "Alice")],
        connector_map={"connector-1": "Connector One"},
        quota_payload=[
            {
                "scope_type": "member",
                "scope_key": "user-1",
                "user_id": "user-1",
                "token_quota": 100,
                "token_used": 40,
            },
            {
                "scope_type": "team",
                "scope_key": "team-1",
                "token_quota": 1000,
                "token_used": 250,
            },
            {
                "scope_type": "connector",
                "scope_key": "connector-missing",
                "connector_id": "connector-missing",
                "token_quota": 80,
                "token_used": 80,
            },
        ],
    )

    assert [record.scope_key for record in records] == ["user-1", "connector-1", "team-1", "connector-missing"]
    assert records[0].display_name == "Alice"
    assert records[0].token_remaining == 60
    assert records[1].connector_display_name == "Connector One"
    assert records[1].token_quota == 0
    assert records[2].scope_type == "team"
    assert records[3].status == "exhausted"


def test_build_quota_records_adds_default_team_record_when_payload_is_missing() -> None:
    records = build_quota_records(
        "team-1",
        members=[],
        connector_map={},
        quota_payload=[],
    )

    assert len(records) == 1
    assert records[0].scope_type == "team"
    assert records[0].scope_key == "team-1"
    assert records[0].token_quota == 0
    assert records[0].status == "active"
