from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_admin_access
from backend.app.models.governance import (
    PlatformAssetCreateRequest,
    PlatformAssetDeleteResponse,
    PlatformAssetForkRequest,
    PlatformAssetMutationResponse,
    PlatformAssetPublishRequest,
    PlatformAssetReviewRequest,
    PlatformAssetsResponse,
)
from backend.app.services.governance_asset_payloads import SUPPORTED_PLATFORM_ASSET_TYPES
from backend.app.services.service_registry import get_governance_store


router = APIRouter(tags=["team"])


def asset_type_allows_results(asset_type: str | None) -> bool:
    return asset_type is None or asset_type in SUPPORTED_PLATFORM_ASSET_TYPES



@router.get("/assets", response_model=PlatformAssetsResponse)
def list_team_assets(
    asset_type: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    category: str | None = Query(default=None),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> PlatformAssetsResponse:
    if not asset_type_allows_results(asset_type):
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
        raise_store_http_error(exc)
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
        raise_store_http_error(exc)
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
        raise_store_http_error(exc)
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
        raise_store_http_error(exc)
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
        raise_store_http_error(exc)
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
        raise_store_http_error(exc)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return PlatformAssetDeleteResponse(deleted=True, asset_id=asset_id)
