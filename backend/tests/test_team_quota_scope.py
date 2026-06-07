from __future__ import annotations

from backend.app.models.governance import TeamQuotaScopeAdjustRequest
from backend.app.services.team_quota_scope import resolve_quota_scope_key


def test_member_quota_scope_prefers_user_id_over_scope_key() -> None:
    payload = TeamQuotaScopeAdjustRequest(
        scope_type="member",
        scope_key="legacy-member",
        user_id="user-1",
    )

    assert resolve_quota_scope_key(payload, team_id="team-1") == "user-1"


def test_connector_quota_scope_prefers_connector_id_over_scope_key() -> None:
    payload = TeamQuotaScopeAdjustRequest(
        scope_type="connector",
        scope_key="legacy-connector",
        connector_id="connector-1",
    )

    assert resolve_quota_scope_key(payload, team_id="team-1") == "connector-1"


def test_team_quota_scope_defaults_to_team_id() -> None:
    payload = TeamQuotaScopeAdjustRequest(scope_type="team")

    assert resolve_quota_scope_key(payload, team_id="team-1") == "team-1"


def test_member_quota_scope_without_identity_is_missing() -> None:
    payload = TeamQuotaScopeAdjustRequest(scope_type="member")

    assert resolve_quota_scope_key(payload, team_id="team-1") is None
