from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.governance import TeamMemberRecord, TeamProfileRecord
from backend.app.services.governance_usage import GovernanceUsageRepository


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


class MemberLookup:
    def __init__(self, members: list[TeamMemberRecord]) -> None:
        self.members = members
        self.calls: list[tuple[str, str]] = []

    def __call__(self, team_id: str, *, access_token: str) -> list[TeamMemberRecord]:
        self.calls.append((team_id, access_token))
        return self.members


class ProfileLookup:
    def __init__(self, profiles: list[TeamProfileRecord]) -> None:
        self.profiles = {profile.user_id: profile for profile in profiles}
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, user_ids: list[str], *, access_token: str) -> list[TeamProfileRecord]:
        self.calls.append((user_ids, access_token))
        return [self.profiles[user_id] for user_id in user_ids if user_id in self.profiles]


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


def _repository(
    responses: list[Any],
    *,
    members: list[TeamMemberRecord] | None = None,
    profiles: list[TeamProfileRecord] | None = None,
) -> tuple[GovernanceUsageRepository, RequestRecorder, MemberLookup, ProfileLookup]:
    request = RequestRecorder(responses)
    member_lookup = MemberLookup(members or [])
    profile_lookup = ProfileLookup(profiles or [])
    return (
        GovernanceUsageRepository(
            request_json=request,
            list_members=member_lookup,
            list_profiles=profile_lookup,
        ),
        request,
        member_lookup,
        profile_lookup,
    )


def test_list_quotas_enriches_members_connectors_team_and_unhandled_scopes() -> None:
    repository, request, _, _ = _repository(
        [
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "scope_type": "member",
                    "scope_key": "user-1",
                    "token_quota": 100,
                    "token_used": 40,
                    "status": "active",
                    "warning_threshold": 10,
                    "updated_at": NOW,
                },
                {
                    "team_id": "team-1",
                    "scope_type": "team",
                    "scope_key": "team-1",
                    "token_quota": 1000,
                    "token_used": 250,
                    "status": "active",
                    "updated_at": NOW,
                },
                {
                    "team_id": "team-1",
                    "connector_id": "connector-missing",
                    "scope_type": "connector",
                    "scope_key": "connector-missing",
                    "token_quota": 80,
                    "token_used": 80,
                    "updated_at": NOW,
                },
            ],
            [{"id": "connector-1", "display_name": "Connector One"}],
        ],
        members=[_member("user-1", "Alice")],
    )

    items = repository.list_quotas("team-1", access_token="token")

    assert [item.scope_key for item in items] == ["user-1", "connector-1", "team-1", "connector-missing"]
    assert items[0].display_name == "Alice"
    assert items[0].token_remaining == 60
    assert items[1].connector_display_name == "Connector One"
    assert items[1].token_quota == 0
    assert items[2].scope_type == "team"
    assert items[3].status == "exhausted"
    assert request.calls[0]["path"].startswith("quota_accounts?select=")
    assert request.calls[1]["path"] == "ai_connectors?select=id,display_name&team_id=eq.team-1"


def test_quota_record_projection_preserves_payload_identity_and_status_defaults() -> None:
    quota = GovernanceUsageRepository._quota_record_from_payload(
        "team-1",
        {
            "user_id": "user-payload",
            "connector_id": "connector-payload",
            "connector_display_name": "Connector Payload",
            "token_quota": "5",
            "token_used": "9",
            "warning_threshold": "invalid",
            "updated_at": NOW,
        },
    )

    assert quota.scope_type == "team"
    assert quota.scope_key == "user-payload"
    assert quota.user_id == "user-payload"
    assert quota.connector_id == "connector-payload"
    assert quota.connector_display_name == "Connector Payload"
    assert quota.token_quota == 5
    assert quota.token_used == 9
    assert quota.token_remaining == 0
    assert quota.status == "exhausted"
    assert quota.warning_threshold == 0
    assert quota.updated_at == NOW


def test_adjust_quota_preserves_existing_values_and_uses_member_filter() -> None:
    repository, request, member_lookup, _ = _repository(
        [
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-2",
                    "scope_type": "member",
                    "scope_key": "user-2",
                    "token_quota": 200,
                    "status": "frozen",
                    "warning_threshold": 25,
                }
            ],
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-2",
                    "scope_type": "member",
                    "scope_key": "user-2",
                    "token_quota": 200,
                    "token_used": 10,
                    "status": "frozen",
                    "warning_threshold": 25,
                    "updated_at": NOW,
                }
            ],
        ],
        members=[_member("user-2", "Bob")],
    )

    quota = repository.adjust_quota("team-1", "user-2", None, access_token="token")

    assert quota.display_name == "Bob"
    assert quota.status == "frozen"
    assert quota.token_remaining == 190
    assert member_lookup.calls == [("team-1", "token")]
    assert "&user_id=eq.user-2&limit=1" in request.calls[0]["path"]
    assert request.calls[1]["method"] == "PATCH"
    assert request.calls[1]["path"] == "quota_accounts?team_id=eq.team-1&user_id=eq.user-2"
    assert request.calls[1]["body"] == {
        "team_id": "team-1",
        "user_id": "user-2",
        "connector_id": None,
        "scope_type": "member",
        "scope_key": "user-2",
        "token_quota": 200,
        "status": "frozen",
        "warning_threshold": 25,
    }


def test_adjust_quota_reactivates_exhausted_quota_when_limit_increases() -> None:
    repository, request, _, _ = _repository(
        [
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-2",
                    "scope_type": "member",
                    "scope_key": "user-2",
                    "token_quota": 100,
                    "token_used": 100,
                    "status": "exhausted",
                    "warning_threshold": 0,
                }
            ],
            [
                {
                    "team_id": "team-1",
                    "user_id": "user-2",
                    "scope_type": "member",
                    "scope_key": "user-2",
                    "token_quota": 200,
                    "token_used": 100,
                    "status": "active",
                    "warning_threshold": 0,
                    "updated_at": NOW,
                }
            ],
        ],
        members=[_member("user-2", "Bob")],
    )

    quota = repository.adjust_quota("team-1", "user-2", 200, access_token="token")

    assert quota.status == "active"
    assert quota.token_remaining == 100
    assert request.calls[1]["body"]["status"] == "active"


def test_adjust_quota_scope_sets_connector_identity_on_insert() -> None:
    repository, request, _, _ = _repository(
        [
            [],
            {
                "team_id": "team-1",
                "connector_id": "connector-1",
                "scope_type": "connector",
                "scope_key": "connector-1",
                "token_quota": 400,
                "token_used": 0,
                "status": "active",
                "warning_threshold": 50,
                "updated_at": NOW,
            },
        ]
    )

    quota = repository.adjust_quota_scope(
        "team-1",
        scope_type="connector",
        scope_key="connector-1",
        token_quota=400,
        warning_threshold=50,
        access_token="token",
    )

    assert quota.connector_id == "connector-1"
    assert quota.token_quota == 400
    assert request.calls[1]["method"] == "POST"
    assert request.calls[1]["path"] == "quota_accounts"
    assert request.calls[1]["body"]["user_id"] is None
    assert request.calls[1]["body"]["connector_id"] == "connector-1"


def test_list_token_ledgers_caps_limit_and_enriches_related_names() -> None:
    repository, request, _, profile_lookup = _repository(
        [
            [
                {
                    "id": "ledger-1",
                    "team_id": "team-1",
                    "user_id": "user-1",
                    "task_id": "task-1",
                    "connector_id": "connector-1",
                    "phase": "codex",
                    "stage_key": "codex_native",
                    "source_key": "workspace-1",
                    "model_name": "codex-model",
                    "input_tokens": 12,
                    "output_tokens": 8,
                    "total_tokens": 20,
                    "calculation_method": "artifact",
                    "raw_usage": {"total_tokens": 20},
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            [{"id": "task-1", "name": "Task One"}],
            [{"id": "connector-1", "display_name": "Connector One"}],
        ],
        profiles=[_profile("user-1", "Alice")],
    )

    items = repository.list_token_ledgers(
        "team-1",
        access_token="token",
        limit=5000,
        user_id="user-1",
        task_id="task-1",
    )

    assert len(items) == 1
    assert items[0].user_display_name == "Alice"
    assert items[0].task_name == "Task One"
    assert items[0].connector_display_name == "Connector One"
    assert items[0].total_tokens == 20
    assert "limit=1000" in request.calls[0]["path"]
    assert "&user_id=eq.user-1" in request.calls[0]["path"]
    assert "&task_id=eq.task-1" in request.calls[0]["path"]
    assert profile_lookup.calls == [(["user-1"], "token")]
