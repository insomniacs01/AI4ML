from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.app.models.governance import AdminUserUpdateRequest, TeamMemberRecord, TeamQuotaRecord
from backend.app.services.admin_user_management import update_supabase_user_profile


class AdminTargetMemberNotFoundError(RuntimeError):
    pass


class AdminRoleUpdateBlockedError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminUserUpdateResult:
    member: TeamMemberRecord
    quota: TeamQuotaRecord | None


ProfileUpdater = Callable[..., object]


def update_admin_user_record(
    store,
    *,
    team_id: str,
    member_id: str,
    payload: AdminUserUpdateRequest,
    access_token: str,
    update_profile: ProfileUpdater | None = None,
) -> AdminUserUpdateResult:
    existing_member = require_admin_target_member(
        store,
        team_id=team_id,
        member_id=member_id,
        access_token=access_token,
    )
    update_admin_user_profile(
        store,
        member_id=member_id,
        payload=payload,
        update_profile=update_profile,
    )
    member = update_admin_member_record(
        store,
        team_id=team_id,
        member_id=member_id,
        payload=payload,
        existing_member=existing_member,
        access_token=access_token,
    )
    quota = update_admin_member_quota(
        store,
        team_id=team_id,
        member_id=member_id,
        payload=payload,
        access_token=access_token,
    )
    return AdminUserUpdateResult(member=member, quota=quota)


def require_admin_target_member(
    store,
    *,
    team_id: str,
    member_id: str,
    access_token: str,
) -> TeamMemberRecord:
    existing_member = next(
        (
            item
            for item in store.list_members(team_id, access_token=access_token)
            if item.user_id == member_id
        ),
        None,
    )
    if existing_member is None:
        raise AdminTargetMemberNotFoundError("member not found")
    return existing_member


def update_admin_user_profile(
    store,
    *,
    member_id: str,
    payload: AdminUserUpdateRequest,
    update_profile: ProfileUpdater | None = None,
) -> None:
    if payload.display_name is None:
        return
    profile_updater = update_profile or _update_supabase_profile
    profile_updater(store.settings, user_id=member_id, display_name=payload.display_name)


def update_admin_member_record(
    store,
    *,
    team_id: str,
    member_id: str,
    payload: AdminUserUpdateRequest,
    existing_member: TeamMemberRecord,
    access_token: str,
) -> TeamMemberRecord:
    member = existing_member
    if payload.role is not None:
        assert_admin_role_update_allowed(existing_member, payload.role)
        member = store.update_member_role(
            team_id,
            member_id,
            payload.role,
            access_token=access_token,
        )
    if payload.member_status is not None:
        member = store.update_member_status(
            team_id,
            member_id,
            payload.member_status,
            access_token=access_token,
        )
    return member


def assert_admin_role_update_allowed(existing_member: TeamMemberRecord, next_role: str) -> None:
    if next_role == "team_owner":
        raise AdminRoleUpdateBlockedError("team_owner must be assigned through the ownership transfer endpoint.")
    if existing_member.role == "team_owner" and next_role != "team_owner":
        raise AdminRoleUpdateBlockedError("team_owner cannot be changed through this endpoint. Use ownership transfer instead.")


def update_admin_member_quota(
    store,
    *,
    team_id: str,
    member_id: str,
    payload: AdminUserUpdateRequest,
    access_token: str,
) -> TeamQuotaRecord | None:
    if admin_payload_has_quota_update(payload):
        return store.adjust_quota(
            team_id,
            member_id,
            payload.token_quota,
            status=payload.quota_status,
            warning_threshold=payload.warning_threshold,
            access_token=access_token,
        )
    return store.get_member_quota(team_id, member_id, access_token=access_token)


def admin_payload_has_quota_update(payload: AdminUserUpdateRequest) -> bool:
    return payload.token_quota is not None or payload.quota_status is not None or payload.warning_threshold is not None


def _update_supabase_profile(settings, *, user_id: str, display_name: str | None) -> object:
    return update_supabase_user_profile(settings, user_id=user_id, display_name=display_name)
