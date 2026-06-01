from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

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
    PlatformAssetCreateRequest,
    PlatformAssetDeleteResponse,
    PlatformAssetForkRequest,
    PlatformAssetMutationResponse,
    PlatformLimitsRecord,
    PlatformLimitsResponse,
    PlatformAssetPublishRequest,
    PlatformAssetReviewRequest,
    PlatformAssetsResponse,
    TeamInviteRequest,
    TeamInviteResponse,
    TeamOwnershipTransferRequest,
    TeamOwnershipTransferResponse,
    TeamMemberRoleUpdateRequest,
    TeamMemberRoleUpdateResponse,
    TeamMembersResponse,
    TeamMemberStatusUpdateRequest,
    TeamMemberStatusUpdateResponse,
    TeamQuotaAdjustRequest,
    TeamQuotaAdjustResponse,
    TeamQuotaScopeAdjustRequest,
    TeamQuotasResponse,
    TeamSettingsResponse,
    TeamSettingsUpdateRequest,
    TokenLedgersResponse,
)
from backend.app.services.admin_user_management import (
    AdminUserManagementError,
    reset_supabase_user_password,
    update_supabase_user_profile,
)
from backend.app.services.platform_limits import read_platform_limits, save_platform_limits
from backend.app.services.quota_runtime_guard import pause_member_tasks_for_quota, quota_is_exhausted
from backend.app.services.service_registry import get_governance_store, get_task_store


router = APIRouter(tags=["team"])


def _raise_governance_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    raise_store_http_error(exc)


def _validate_routing_update(payload: AIRoutingPoliciesUpdateRequest) -> None:
    for item in payload.items:
        stage = item.stage.strip()
        if item.model_name and item.model_name.strip() and not item.connector_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{stage} 阶段只填写了模型名但没有 connector_id。请显式选择连接器。",
            )


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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
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

    team_name = str(team.get("name", team_access.team_id))
    invite_code = str(team.get("invite_code", ""))
    email_hint = f"发送给 {payload.email}。" if payload.email else "复制给需要加入团队的成员。"
    share_text = f"团队“{team_name}”的邀请码是：{invite_code}。{email_hint}"
    return TeamInviteResponse(
        team_id=team_access.team_id,
        team_name=team_name,
        invite_code=invite_code,
        share_text=share_text,
        detail="邀请码已准备好，可以直接复制分享。",
    )


@router.patch("/members/{member_id}/role", response_model=TeamMemberRoleUpdateResponse)
def update_team_member_role(
    member_id: str,
    payload: TeamMemberRoleUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamMemberRoleUpdateResponse:
    if payload.role == "team_owner":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="team_owner must be assigned through the ownership transfer endpoint.",
        )
    if member_id == team_access.user.id and team_access.role == "team_owner":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="team_owner cannot demote themselves through member role update. Use ownership transfer instead.",
        )
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


@router.get("/quotas", response_model=TeamQuotasResponse)
def list_team_quotas(team_access: TeamAccessContext = Depends(require_team_admin_access)) -> TeamQuotasResponse:
    try:
        items = get_governance_store().list_quotas(team_access.team_id, access_token=team_access.access_token)
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamQuotasResponse(team_id=team_access.team_id, items=items)


@router.post("/quotas/adjust", response_model=TeamQuotaAdjustResponse)
def adjust_team_quota_scope(
    payload: TeamQuotaScopeAdjustRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamQuotaAdjustResponse:
    scope_type = payload.scope_type
    scope_key = payload.scope_key
    if scope_type == "member":
        scope_key = payload.user_id or scope_key
    elif scope_type == "connector":
        scope_key = payload.connector_id or scope_key
    elif scope_type == "team":
        scope_key = scope_key or team_access.team_id
    if not scope_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="quota scope_key is required.")

    store = get_governance_store()
    try:
        quota = store.adjust_quota_scope(
            team_access.team_id,
            scope_type=scope_type,
            scope_key=scope_key,
            token_quota=payload.token_quota,
            status=payload.status,
            warning_threshold=payload.warning_threshold,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamQuotaAdjustResponse(detail="团队配额已更新。", quota=quota)


@router.post("/quotas/{member_id}/adjust", response_model=TeamQuotaAdjustResponse)
def adjust_team_quota(
    member_id: str,
    payload: TeamQuotaAdjustRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamQuotaAdjustResponse:
    store = get_governance_store()
    try:
        quota = store.adjust_quota(
            team_access.team_id,
            member_id,
            payload.token_quota,
            status=payload.status,
            warning_threshold=payload.warning_threshold,
            access_token=team_access.access_token,
        )
        _pause_member_tasks_if_quota_exhausted(quota, member_id, team_access)
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamQuotaAdjustResponse(detail="成员配额已更新。", quota=quota)


@router.put("/admin/users/{member_id}", response_model=AdminUserUpdateResponse)
def update_admin_user(
    member_id: str,
    payload: AdminUserUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> AdminUserUpdateResponse:
    store = get_governance_store()
    member = None
    quota = None
    try:
        existing_member = next(
            (item for item in store.list_members(team_access.team_id, access_token=team_access.access_token) if item.user_id == member_id),
            None,
        )
        if existing_member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
        if payload.display_name is not None:
            update_supabase_user_profile(store.settings, user_id=member_id, display_name=payload.display_name)
        if payload.role is not None:
            if payload.role == "team_owner":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="team_owner must be assigned through the ownership transfer endpoint.",
                )
            if existing_member.role == "team_owner" and payload.role != "team_owner":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="team_owner cannot be changed through this endpoint. Use ownership transfer instead.",
                )
            member = store.update_member_role(team_access.team_id, member_id, payload.role, access_token=team_access.access_token)
        if payload.member_status is not None:
            member = store.update_member_status(
                team_access.team_id,
                member_id,
                payload.member_status,
                access_token=team_access.access_token,
            )
        if payload.token_quota is not None or payload.quota_status is not None or payload.warning_threshold is not None:
            quota = store.adjust_quota(
                team_access.team_id,
                member_id,
                payload.token_quota,
                status=payload.quota_status,
                warning_threshold=payload.warning_threshold,
                access_token=team_access.access_token,
            )
        if member is None:
            member = existing_member
        if quota is None:
            quota = store.get_member_quota(team_access.team_id, member_id, access_token=team_access.access_token)
        _pause_member_tasks_if_quota_exhausted(quota, member_id, team_access)
    except HTTPException:
        raise
    except AdminUserManagementError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return AdminUserUpdateResponse(detail="用户权限与额度已更新。", member=member, quota=quota)


def _pause_member_tasks_if_quota_exhausted(quota, member_id: str, team_access: TeamAccessContext) -> None:
    if not quota_is_exhausted(quota):
        return
    pause_member_tasks_for_quota(get_task_store(), team_access, user_id=member_id)


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
    _validate_routing_update(payload)
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


@router.get("/assets", response_model=PlatformAssetsResponse)
def list_team_assets(
    asset_type: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    category: str | None = Query(default=None),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> PlatformAssetsResponse:
    if asset_type is not None and asset_type not in {"prompt", "plan"}:
        return PlatformAssetsResponse(team_id=team_access.team_id, items=[])
    try:
        items = get_governance_store().list_assets(
            team_access.team_id,
            access_token=team_access.access_token,
            asset_type=asset_type,
            review_status=review_status,
            visibility=visibility,
            category=category,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return PlatformAssetsResponse(team_id=team_access.team_id, items=items)


@router.post("/assets", response_model=PlatformAssetMutationResponse, status_code=status.HTTP_201_CREATED)
def create_team_asset(
    payload: PlatformAssetCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> PlatformAssetMutationResponse:
    store = get_governance_store()
    try:
        asset = store.create_asset(
            team_access.team_id,
            team_access.user.id,
            payload,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return PlatformAssetMutationResponse(detail="资产记录已创建。", asset=asset)


@router.post("/assets/{asset_id}/review", response_model=PlatformAssetMutationResponse)
def review_team_asset(
    asset_id: str,
    payload: PlatformAssetReviewRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> PlatformAssetMutationResponse:
    store = get_governance_store()
    try:
        asset = store.review_asset(
            team_access.team_id,
            asset_id,
            payload,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return PlatformAssetMutationResponse(detail="资产审核状态已更新。", asset=asset)


@router.post("/assets/{asset_id}/publish", response_model=PlatformAssetMutationResponse)
def publish_team_asset(
    asset_id: str,
    payload: PlatformAssetPublishRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> PlatformAssetMutationResponse:
    store = get_governance_store()
    try:
        asset = store.publish_asset(
            team_access.team_id,
            asset_id,
            team_access.user.id,
            payload,
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return PlatformAssetMutationResponse(detail="资产已发布到团队广场。", asset=asset)


@router.post("/assets/{asset_id}/fork", response_model=PlatformAssetMutationResponse, status_code=status.HTTP_201_CREATED)
def fork_team_asset(
    asset_id: str,
    payload: PlatformAssetForkRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> PlatformAssetMutationResponse:
    store = get_governance_store()
    try:
        asset = store.fork_asset(
            team_access.team_id,
            team_access.user.id,
            asset_id,
            payload,
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return PlatformAssetMutationResponse(detail="资产 Fork 已创建。", asset=asset)


@router.delete("/assets/{asset_id}", response_model=PlatformAssetDeleteResponse)
def delete_team_asset(
    asset_id: str,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> PlatformAssetDeleteResponse:
    try:
        deleted = get_governance_store().delete_asset(
            team_access.team_id,
            asset_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return PlatformAssetDeleteResponse(deleted=True, asset_id=asset_id)


@router.get("/token-ledgers", response_model=TokenLedgersResponse)
def list_team_token_ledgers(
    limit: int = Query(default=500, ge=1, le=1000),
    user_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TokenLedgersResponse:
    try:
        items = get_governance_store().list_token_ledgers(
            team_access.team_id,
            access_token=team_access.access_token,
            limit=limit,
            user_id=user_id,
            task_id=task_id,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TokenLedgersResponse(
        team_id=team_access.team_id,
        items=items,
        total_tokens=sum(item.total_tokens for item in items),
        input_tokens=sum(item.input_tokens for item in items),
        output_tokens=sum(item.output_tokens for item in items),
    )
