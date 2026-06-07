from __future__ import annotations

import pytest

from backend.app.services.team_member_role_rules import assert_member_role_update_allowed, role_value


def test_member_role_update_rejects_team_owner_assignment() -> None:
    with pytest.raises(ValueError, match="ownership transfer"):
        assert_member_role_update_allowed(
            target_member_id="user-2",
            requested_role="team_owner",
            actor_user_id="admin-1",
            actor_role="admin",
        )


def test_member_role_update_rejects_team_owner_self_demotion() -> None:
    with pytest.raises(ValueError, match="cannot demote themselves"):
        assert_member_role_update_allowed(
            target_member_id="owner-1",
            requested_role="admin",
            actor_user_id="owner-1",
            actor_role="team_owner",
        )


def test_member_role_update_allows_admin_updating_another_member() -> None:
    assert_member_role_update_allowed(
        target_member_id="user-2",
        requested_role="developer_user",
        actor_user_id="admin-1",
        actor_role="admin",
    )


def test_role_value_normalizes_enums_and_none() -> None:
    class Role:
        value = "team_owner"

    assert role_value(Role()) == "team_owner"
    assert role_value(None) == ""
