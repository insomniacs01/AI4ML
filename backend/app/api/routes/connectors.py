from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_admin_access
from backend.app.api.errors import raise_store_http_error
from backend.app.models.connector import (
    ConnectorActivateResponse,
    ConnectorCreateRequest,
    ConnectorDeactivateResponse,
    ConnectorDeleteResponse,
    ConnectorHealthCheckResponse,
    ConnectorListResponse,
    ConnectorRecord,
    ConnectorTestResponse,
    ConnectorUpdateRequest,
)
from backend.app.services.connector_health import probe_and_save_connector, probe_and_save_connectors
from backend.app.services.connector_runtime import normalize_provider_config
from backend.app.services.service_registry import get_connector_store


router = APIRouter(prefix="/connectors", tags=["connectors"])



@router.get("", response_model=ConnectorListResponse)
def list_connectors(team_access: TeamAccessContext = Depends(require_team_access)) -> ConnectorListResponse:
    try:
        items = [
            connector.to_public()
            for connector in get_connector_store().list_connectors(
                team_access.team_id,
                access_token=team_access.access_token,
            )
        ]
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return ConnectorListResponse(items=items)


@router.post("", response_model=ConnectorRecord, status_code=status.HTTP_201_CREATED)
def create_connector(
    payload: ConnectorCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorRecord:
    try:
        normalized_base_url, normalized_wire_api = normalize_provider_config(
            endpoint_url=payload.endpoint_url,
            base_url=payload.base_url,
            wire_api=payload.wire_api,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        connector = get_connector_store().create_connector(
            payload,
            team_id=team_access.team_id,
            created_by=team_access.user.id,
            normalized_base_url=normalized_base_url,
            normalized_wire_api=normalized_wire_api,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return connector.to_public()


@router.post("/health-check", response_model=ConnectorHealthCheckResponse)
def health_check_connectors(
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorHealthCheckResponse:
    connector_store = get_connector_store()
    try:
        results = probe_and_save_connectors(
            connector_store,
            team_id=team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

    return ConnectorHealthCheckResponse(detail="连接器批量健康检查已完成。", items=results)


@router.patch("/{connector_id}", response_model=ConnectorRecord)
def update_connector(
    connector_id: str,
    payload: ConnectorUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorRecord:
    connector_store = get_connector_store()
    try:
        connector = connector_store.get_connector(
            team_access.team_id,
            connector_id,
            access_token=team_access.access_token,
        )
        if connector is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connector not found")
        normalized_base_url = None
        normalized_wire_api = None
        if payload.endpoint_url is not None or payload.base_url is not None or payload.wire_api is not None:
            try:
                normalized_base_url, normalized_wire_api = normalize_provider_config(
                    endpoint_url=payload.endpoint_url if payload.endpoint_url is not None else connector.endpoint_url,
                    base_url=payload.base_url if payload.base_url is not None else connector.base_url,
                    wire_api=payload.wire_api or connector.wire_api.value,
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        updated = connector_store.update_connector(
            connector,
            payload,
            normalized_base_url=normalized_base_url,
            normalized_wire_api=normalized_wire_api,
            access_token=team_access.access_token,
        )
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return updated.to_public()


@router.post("/{connector_id}/test", response_model=ConnectorTestResponse)
def test_connector(
    connector_id: str,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorTestResponse:
    connector_store = get_connector_store()
    try:
        connector = connector_store.get_connector(
            team_access.team_id,
            connector_id,
            access_token=team_access.access_token,
        )
        if connector is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connector not found")

        result = probe_and_save_connector(
            connector_store,
            connector,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

    return result


@router.post("/{connector_id}/activate", response_model=ConnectorActivateResponse)
def set_connector_as_runtime(
    connector_id: str,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorActivateResponse:
    try:
        connector = get_connector_store().activate_connector(
            team_access.team_id,
            connector_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

    return ConnectorActivateResponse(
        detail="连接器已设为当前团队运行时。后续这个团队的 AI 解析和 Codex 任务协作都会优先使用它。",
        connector=connector.to_public(),
    )


@router.post("/{connector_id}/deactivate", response_model=ConnectorDeactivateResponse)
def deactivate_connector(
    connector_id: str,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorDeactivateResponse:
    try:
        connector = get_connector_store().deactivate_connector(
            team_access.team_id,
            connector_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

    return ConnectorDeactivateResponse(
        detail="连接器已停用为非当前运行时。后续任务必须显式选择其他阶段路由或激活新的连接器。",
        connector=connector.to_public(),
    )


@router.delete("/{connector_id}", response_model=ConnectorDeleteResponse)
def delete_connector(
    connector_id: str,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorDeleteResponse:
    try:
        connector = get_connector_store().get_connector(
            team_access.team_id,
            connector_id,
            access_token=team_access.access_token,
        )
        if connector is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connector not found")
        get_connector_store().delete_connector(
            team_access.team_id,
            connector_id,
            access_token=team_access.access_token,
        )
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

    return ConnectorDeleteResponse(deleted=True, connector_id=connector_id, detail="连接器已删除。")
