from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from backend.app.api.routes import team as team_routes
from backend.app.models.governance import (
    AdminUserUpdateRequest,
    TeamMemberRecord,
    TeamProfileRecord,
    TeamQuotaRecord,
)
from backend.app.services.team_admin_user_update import (
    AdminRoleUpdateBlockedError,
    AdminTargetMemberNotFoundError,
    update_admin_user_record,
)


def _member(user_id: str = "user-2", *, role: str = "member", status: str = "active") -> TeamMemberRecord:
    return TeamMemberRecord(
        team_id="team-1",
        user_id=user_id,
        role=role,
        member_status=status,
        profile=TeamProfileRecord(user_id=user_id, display_name="Member"),
    )


def _quota(*, status: str = "active", remaining: int = 10) -> TeamQuotaRecord:
    return TeamQuotaRecord(
        team_id="team-1",
        scope_type="member",
        scope_key="user-2",
        user_id="user-2",
        token_quota=100,
        token_used=100 - remaining,
        token_remaining=remaining,
        status=status,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _team_access() -> SimpleNamespace:
    return SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="admin-1"),
    )


class _AdminUserStore:
    def __init__(self, existing_member: TeamMemberRecord, quota: TeamQuotaRecord | None = None) -> None:
        self.settings = SimpleNamespace()
        self.existing_member = existing_member
        self.quota = quota
        self.update_member_role = Mock(side_effect=self._update_role)
        self.update_member_status = Mock(side_effect=self._update_status)
        self.adjust_quota = Mock(side_effect=self._adjust_quota)
        self.get_member_quota = Mock(return_value=quota)

    def list_members(self, team_id: str, *, access_token: str) -> list[TeamMemberRecord]:
        assert team_id == "team-1"
        assert access_token == "token"
        return [self.existing_member]

    def _update_role(self, team_id: str, member_id: str, role: str, *, access_token: str) -> TeamMemberRecord:
        return self.existing_member.model_copy(update={"role": role})

    def _update_status(self, team_id: str, member_id: str, member_status: str, *, access_token: str) -> TeamMemberRecord:
        return self.existing_member.model_copy(update={"member_status": member_status})

    def _adjust_quota(
        self,
        team_id: str,
        member_id: str,
        token_quota: int | None,
        *,
        status: str | None = None,
        warning_threshold: int | None = None,
        access_token: str,
    ) -> TeamQuotaRecord:
        return self.quota or _quota(status=status or "active", remaining=0 if status == "exhausted" else 10)


def test_update_admin_user_rejects_team_owner_assignment(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _AdminUserStore(_member())
    monkeypatch.setattr(team_routes, "get_governance_store", lambda: store)

    with pytest.raises(HTTPException) as exc:
        team_routes.update_admin_user(
            "user-2",
            AdminUserUpdateRequest(role="team_owner"),
            _team_access(),
        )

    assert exc.value.status_code == 422
    store.update_member_role.assert_not_called()


def test_update_admin_user_rejects_existing_owner_role_change(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _AdminUserStore(_member(role="team_owner"))
    monkeypatch.setattr(team_routes, "get_governance_store", lambda: store)

    with pytest.raises(HTTPException) as exc:
        team_routes.update_admin_user(
            "user-2",
            AdminUserUpdateRequest(role="admin"),
            _team_access(),
        )

    assert exc.value.status_code == 422
    store.update_member_role.assert_not_called()


def test_update_admin_user_applies_profile_member_quota_and_pauses_exhausted_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exhausted_quota = _quota(status="exhausted", remaining=0)
    store = _AdminUserStore(_member(), quota=exhausted_quota)
    update_profile = Mock()
    pause_tasks = Mock()
    monkeypatch.setattr(team_routes, "get_governance_store", lambda: store)
    monkeypatch.setattr("backend.app.services.team_admin_user_update.update_supabase_user_profile", update_profile)
    monkeypatch.setattr(team_routes, "pause_member_tasks_if_quota_exhausted", pause_tasks)

    response = team_routes.update_admin_user(
        "user-2",
        AdminUserUpdateRequest(
            display_name="New name",
            role="developer_user",
            member_status="frozen",
            token_quota=100,
            quota_status="exhausted",
            warning_threshold=5,
        ),
        _team_access(),
    )

    update_profile.assert_called_once_with(store.settings, user_id="user-2", display_name="New name")
    store.update_member_role.assert_called_once()
    store.update_member_status.assert_called_once()
    store.adjust_quota.assert_called_once()
    pause_tasks.assert_called_once_with(exhausted_quota, "user-2", _team_access())
    assert response.member.member_status == "frozen"
    assert response.quota == exhausted_quota


def test_update_admin_user_record_applies_profile_member_and_quota_updates() -> None:
    exhausted_quota = _quota(status="exhausted", remaining=0)
    store = _AdminUserStore(_member(), quota=exhausted_quota)
    update_profile = Mock()

    result = update_admin_user_record(
        store,
        team_id="team-1",
        member_id="user-2",
        payload=AdminUserUpdateRequest(
            display_name="New name",
            role="developer_user",
            member_status="frozen",
            token_quota=100,
            quota_status="exhausted",
            warning_threshold=5,
        ),
        access_token="token",
        update_profile=update_profile,
    )

    update_profile.assert_called_once_with(store.settings, user_id="user-2", display_name="New name")
    store.update_member_role.assert_called_once_with("team-1", "user-2", "developer_user", access_token="token")
    store.update_member_status.assert_called_once_with("team-1", "user-2", "frozen", access_token="token")
    store.adjust_quota.assert_called_once_with(
        "team-1",
        "user-2",
        100,
        status="exhausted",
        warning_threshold=5,
        access_token="token",
    )
    store.get_member_quota.assert_not_called()
    assert result.member.member_status == "frozen"
    assert result.quota == exhausted_quota


def test_update_admin_user_record_reads_existing_quota_without_quota_changes() -> None:
    existing_quota = _quota(status="active", remaining=10)
    store = _AdminUserStore(_member(), quota=existing_quota)
    update_profile = Mock()

    result = update_admin_user_record(
        store,
        team_id="team-1",
        member_id="user-2",
        payload=AdminUserUpdateRequest(),
        access_token="token",
        update_profile=update_profile,
    )

    update_profile.assert_not_called()
    store.update_member_role.assert_not_called()
    store.update_member_status.assert_not_called()
    store.adjust_quota.assert_not_called()
    store.get_member_quota.assert_called_once_with("team-1", "user-2", access_token="token")
    assert result.member.user_id == "user-2"
    assert result.quota == existing_quota


def test_update_admin_user_record_rejects_team_owner_assignment() -> None:
    store = _AdminUserStore(_member())

    with pytest.raises(AdminRoleUpdateBlockedError, match="ownership transfer"):
        update_admin_user_record(
            store,
            team_id="team-1",
            member_id="user-2",
            payload=AdminUserUpdateRequest(role="team_owner"),
            access_token="token",
            update_profile=Mock(),
        )

    store.update_member_role.assert_not_called()
    store.adjust_quota.assert_not_called()


def test_update_admin_user_record_requires_existing_member() -> None:
    store = _AdminUserStore(_member(user_id="other-user"))

    with pytest.raises(AdminTargetMemberNotFoundError, match="member not found"):
        update_admin_user_record(
            store,
            team_id="team-1",
            member_id="user-2",
            payload=AdminUserUpdateRequest(),
            access_token="token",
            update_profile=Mock(),
        )
