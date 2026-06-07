from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import (
    TeamAccessContext,
    require_team_access,
    require_team_admin_access,
    require_team_owner_access,
)
from backend.app.models.governance import (
    AdminPasswordResetRequest,
    AdminPasswordResetResponse,
    AdminUserUpdateRequest,
    AdminUserUpdateResponse,
    AIRoutingPoliciesResponse,
    AIRoutingPoliciesUpdateRequest,
    AIRoutingPoliciesUpdateResponse,
    PlatformLimitsRecord,
    PlatformLimitsResponse,
    TeamInviteRequest,
    TeamInviteResponse,
    TeamOwnershipTransferRequest,
    TeamOwnershipTransferResponse,
    TeamMemberRoleUpdateRequest,
    TeamMemberRoleUpdateResponse,
    TeamMembersResponse,
    TeamMemberStatusUpdateRequest,
    TeamMemberStatusUpdateResponse,
    TeamSettingsResponse,
    TeamSettingsUpdateRequest,
)
from backend.app.services.admin_user_management import (
    AdminUserManagementError,
    reset_supabase_user_password,
)
from backend.app.services.platform_limits import read_platform_limits, save_platform_limits
from backend.app.services.service_registry import get_governance_store
from backend.app.services.team_admin_user_update import (
    AdminRoleUpdateBlockedError,
    AdminTargetMemberNotFoundError,
    update_admin_user_record,
)
from backend.app.services.team_invite import build_team_invite_response
from backend.app.services.team_member_role_rules import assert_member_role_update_allowed
from backend.app.services.team_quota_enforcement import pause_member_tasks_if_quota_exhausted
from backend.app.services.team_routing_policy_validation import validate_routing_update


router = APIRouter(tags=["team"])


def _raise_governance_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    raise_store_http_error(exc)


@router.get("/members", response_model=TeamMembersResponse)
def list_team_members(team_access: TeamAccessContext = Depends(require_team_access)) -> TeamMembersResponse:
    try:
        items = get_governance_store().list_members(team_access.team_id, access_token=team_access.access_token)
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamMembersResponse(team_id=team_access.team_id, items=items)


@router.get("/settings", response_model=TeamSettingsResponse)
def get_team_settings(team_access: TeamAccessContext = Depends(require_team_access)) -> TeamSettingsResponse:
    try:
        team = get_governance_store().get_team_settings(
            team_access.team_id,
            access_token=team_access.access_token,
        )
        if team is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="team not found")
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamSettingsResponse(team=team)


@router.patch("/settings", response_model=TeamSettingsResponse)
def update_team_settings(
    payload: TeamSettingsUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_owner_access),
) -> TeamSettingsResponse:
    store = get_governance_store()
    try:
        team = store.update_team_settings(
            team_access.team_id,
            payload,
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamSettingsResponse(team=team)


@router.post("/owner/transfer", response_model=TeamOwnershipTransferResponse)
def transfer_team_ownership(
    payload: TeamOwnershipTransferRequest,
    team_access: TeamAccessContext = Depends(require_team_owner_access),
) -> TeamOwnershipTransferResponse:
    store = get_governance_store()
    try:
        team, previous_owner, new_owner = store.transfer_ownership(
            team_access.team_id,
            current_owner_id=team_access.user.id,
            new_owner_user_id=payload.new_owner_user_id,
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamOwnershipTransferResponse(
        detail="团队所有权已转移。",
        team=team,
        previous_owner=previous_owner,
        new_owner=new_owner,
    )


@router.post("/members/invite", response_model=TeamInviteResponse)
def get_team_invite_details(
    payload: TeamInviteRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamInviteResponse:
    store = get_governance_store()
    try:
        team = store.get_team(team_access.team_id, access_token=team_access.access_token)
        if team is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="team not found")
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)

    return build_team_invite_response(
        team_id=team_access.team_id,
        team=team,
        email=payload.email,
    )


@router.patch("/members/{member_id}/role", response_model=TeamMemberRoleUpdateResponse)
def update_team_member_role(
    member_id: str,
    payload: TeamMemberRoleUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamMemberRoleUpdateResponse:
    try:
        assert_member_role_update_allowed(
            target_member_id=member_id,
            requested_role=payload.role,
            actor_user_id=team_access.user.id,
            actor_role=team_access.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    store = get_governance_store()
    try:
        member = store.update_member_role(
            team_access.team_id,
            member_id,
            payload.role,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamMemberRoleUpdateResponse(detail="成员角色已更新。", member=member)


@router.patch("/members/{member_id}/status", response_model=TeamMemberStatusUpdateResponse)
def update_team_member_status(
    member_id: str,
    payload: TeamMemberStatusUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamMemberStatusUpdateResponse:
    store = get_governance_store()
    try:
        member = store.update_member_status(
            team_access.team_id,
            member_id,
            payload.member_status,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamMemberStatusUpdateResponse(detail="成员状态已更新。", member=member)


@router.put("/admin/users/{member_id}", response_model=AdminUserUpdateResponse)
def update_admin_user(
    member_id: str,
    payload: AdminUserUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> AdminUserUpdateResponse:
    store = get_governance_store()
    try:
        result = update_admin_user_record(
            store,
            team_id=team_access.team_id,
            member_id=member_id,
            payload=payload,
            access_token=team_access.access_token,
        )
        pause_member_tasks_if_quota_exhausted(result.quota, member_id, team_access)
    except AdminTargetMemberNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminRoleUpdateBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except AdminUserManagementError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return AdminUserUpdateResponse(detail="用户权限与额度已更新。", member=result.member, quota=result.quota)


@router.post("/admin/users/{member_id}/reset-password", response_model=AdminPasswordResetResponse)
def reset_admin_user_password(
    member_id: str,
    payload: AdminPasswordResetRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> AdminPasswordResetResponse:
    try:
        reset_supabase_user_password(get_governance_store().settings, user_id=member_id, password=payload.password)
    except AdminUserManagementError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return AdminPasswordResetResponse(detail="用户密码已重置。", user_id=member_id)


@router.get("/admin/platform-limits", response_model=PlatformLimitsResponse)
def get_admin_platform_limits(
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> PlatformLimitsResponse:
    return PlatformLimitsResponse(**read_platform_limits(get_governance_store().settings).model_dump())


@router.put("/admin/platform-limits", response_model=PlatformLimitsResponse)
def update_admin_platform_limits(
    payload: PlatformLimitsRecord,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> PlatformLimitsResponse:
    limits = save_platform_limits(get_governance_store().settings, payload)
    return PlatformLimitsResponse(**limits.model_dump())


@router.get("/routing", response_model=AIRoutingPoliciesResponse)
def list_team_routing(team_access: TeamAccessContext = Depends(require_team_access)) -> AIRoutingPoliciesResponse:
    try:
        items = get_governance_store().list_routing_policies(
            team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return AIRoutingPoliciesResponse(team_id=team_access.team_id, items=items)


@router.put("/routing", response_model=AIRoutingPoliciesUpdateResponse)
def save_team_routing(
    payload: AIRoutingPoliciesUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> AIRoutingPoliciesUpdateResponse:
    try:
        validate_routing_update(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    store = get_governance_store()
    try:
        items = store.save_routing_policies(
            team_access.team_id,
            team_access.user.id,
            payload,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return AIRoutingPoliciesUpdateResponse(
        detail="默认 AI 路由已更新。",
        team_id=team_access.team_id,
        items=items,
    )
