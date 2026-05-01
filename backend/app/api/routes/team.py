from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import (
    TeamAccessContext,
    require_team_access,
    require_team_admin_access,
)
from backend.app.models.governance import (
    AIRoutingPoliciesResponse,
    AIRoutingPoliciesUpdateRequest,
    AIRoutingPoliciesUpdateResponse,
    AuditLogsResponse,
    PlatformAssetCreateRequest,
    PlatformAssetForkRequest,
    PlatformAssetMutationResponse,
    PlatformAssetPublishRequest,
    PlatformAssetReviewRequest,
    PlatformAssetsResponse,
    TeamInviteRequest,
    TeamInviteResponse,
    TeamMemberRoleUpdateRequest,
    TeamMemberRoleUpdateResponse,
    TeamMembersResponse,
    TeamMemberStatusUpdateRequest,
    TeamMemberStatusUpdateResponse,
    TeamQuotaAdjustRequest,
    TeamQuotaAdjustResponse,
    TeamQuotasResponse,
)
from backend.app.services.governance_store import GovernanceStore


router = APIRouter(prefix="/team", tags=["team"])


@lru_cache
def get_governance_store() -> GovernanceStore:
    return GovernanceStore(get_settings())


def _raise_governance_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _validate_routing_update(payload: AIRoutingPoliciesUpdateRequest) -> None:
    for item in payload.items:
        stage = item.stage.strip()
        if item.fallback_connector_id or (item.fallback_model_name and item.fallback_model_name.strip()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{stage} 阶段仍提交了 fallback 路由。当前运行链路要求显式主路由失败即失败，不再保存备用路由。",
            )
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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.invite.prepare",
            resource_type="team",
            resource_id=team_access.team_id,
            detail={"email": payload.email, "note": payload.note},
            access_token=team_access.access_token,
        )
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
    store = get_governance_store()
    try:
        member = store.update_member_role(
            team_access.team_id,
            member_id,
            payload.role,
            access_token=team_access.access_token,
        )
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.member.role.update",
            resource_type="team_member",
            resource_id=member_id,
            detail={"next_role": payload.role},
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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.member.status.update",
            resource_type="team_member",
            resource_id=member_id,
            detail={"next_status": payload.member_status},
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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.quota.adjust",
            resource_type="quota_account",
            resource_id=member_id,
            detail={
                "token_quota": payload.token_quota,
                "status": payload.status,
                "warning_threshold": payload.warning_threshold,
            },
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return TeamQuotaAdjustResponse(detail="成员配额已更新。", quota=quota)


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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.routing.update",
            resource_type="ai_routing_policy",
            resource_id=team_access.team_id,
            detail={
                "stages": [
                    {
                        "stage": item.stage,
                        "connector_id": item.connector_id,
                        "model_name": item.model_name,
                    }
                    for item in payload.items
                ]
            },
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
    team_access: TeamAccessContext = Depends(require_team_access),
) -> PlatformAssetsResponse:
    try:
        items = get_governance_store().list_assets(
            team_access.team_id,
            access_token=team_access.access_token,
            asset_type=asset_type,
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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.asset.create",
            resource_type=payload.asset_type,
            resource_id=asset.id,
            detail={"title": payload.title, "review_status": payload.review_status},
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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.asset.review",
            resource_type=str(asset.asset_type),
            resource_id=asset.id,
            detail={"review_status": payload.review_status, "note": payload.note},
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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.asset.publish",
            resource_type=str(asset.asset_type),
            resource_id=asset.id,
            detail={"note": payload.note},
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
        store.create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action="team.asset.fork",
            resource_type=str(asset.asset_type),
            resource_id=asset.id,
            detail={
                "source_asset_id": asset_id,
                "title": asset.title,
                "review_status": asset.review_status,
            },
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return PlatformAssetMutationResponse(detail="资产 Fork 已创建。", asset=asset)


@router.get("/audit-logs", response_model=AuditLogsResponse)
def list_team_audit_logs(team_access: TeamAccessContext = Depends(require_team_admin_access)) -> AuditLogsResponse:
    try:
        items = get_governance_store().list_audit_logs(
            team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return AuditLogsResponse(team_id=team_access.team_id, items=items)
