from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_admin_access
from backend.app.models.connector import (
    ConnectorActivateResponse,
    ConnectorCreateRequest,
    ConnectorDeactivateResponse,
    ConnectorDeleteResponse,
    ConnectorHealthCheckResponse,
    ConnectorListResponse,
    ConnectorRecord,
    ConnectorTestStatus,
    ConnectorTestResponse,
    ConnectorUpdateRequest,
)
from backend.app.services.connector_runtime import normalize_provider_config, probe_provider
from backend.app.services.connector_store import ConnectorStore
from backend.app.services.governance_store import GovernanceStore


router = APIRouter(prefix="/connectors", tags=["connectors"])


@lru_cache
def get_connector_store() -> ConnectorStore:
    return ConnectorStore(get_settings())


@lru_cache
def get_governance_store() -> GovernanceStore:
    return GovernanceStore(get_settings())


def _raise_connector_store_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _write_connector_audit(
    team_access: TeamAccessContext,
    *,
    action: str,
    connector_id: str,
    detail: dict,
) -> None:
    try:
        get_governance_store().create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action=action,
            resource_type="ai_connector",
            resource_id=connector_id,
            detail=detail,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError):
        pass


def _probe_and_save_connector(
    connector_store: ConnectorStore,
    connector,
    *,
    team_access: TeamAccessContext,
) -> tuple[bool, str, bool, bool, ConnectorRecord]:
    settings = get_settings()
    result = probe_provider(
        base_url=connector.base_url,
        api_key=connector.api_key,
        model_name=connector.model_name,
        wire_api=connector.wire_api,
        timeout_seconds=settings.mlzero_provider_request_timeout_seconds,
        user_agent=settings.mlzero_provider_user_agent,
    )
    connector.last_test_status = ConnectorTestStatus.passed if result.ok else ConnectorTestStatus.failed
    connector.last_test_detail = result.detail
    connector.last_tested_at = datetime.now(timezone.utc)
    connector = connector_store.save_connector(connector, access_token=team_access.access_token)
    return result.ok, result.detail, result.model_listed, result.inference_ok, connector.to_public()


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
        _raise_connector_store_http_error(exc)
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
        _write_connector_audit(
            team_access,
            action="connector.create",
            connector_id=connector.id,
            detail={
                "display_name": connector.display_name,
                "base_url": connector.base_url,
                "model_name": connector.model_name,
                "wire_api": connector.wire_api.value,
                "api_key_storage": "encrypted",
            },
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)
    return connector.to_public()


@router.post("/health-check", response_model=ConnectorHealthCheckResponse)
def health_check_connectors(
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> ConnectorHealthCheckResponse:
    connector_store = get_connector_store()
    try:
        connectors = connector_store.list_connectors(
            team_access.team_id,
            access_token=team_access.access_token,
        )
        results: list[ConnectorTestResponse] = []
        for connector in connectors:
            ok, detail, model_listed, inference_ok, public_connector = _probe_and_save_connector(
                connector_store,
                connector,
                team_access=team_access,
            )
            results.append(
                ConnectorTestResponse(
                    ok=ok,
                    detail=detail,
                    model_listed=model_listed,
                    inference_ok=inference_ok,
                    connector=public_connector,
                )
            )
        _write_connector_audit(
            team_access,
            action="connector.health_check",
            connector_id=team_access.team_id,
            detail={
                "checked_count": len(results),
                "passed_count": sum(1 for item in results if item.ok),
            },
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)

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
        _write_connector_audit(
            team_access,
            action="connector.update",
            connector_id=updated.id,
            detail={
                "display_name": updated.display_name,
                "base_url": updated.base_url,
                "model_name": updated.model_name,
                "wire_api": updated.wire_api.value,
            },
        )
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)
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

        ok, detail, model_listed, inference_ok, public_connector = _probe_and_save_connector(
            connector_store,
            connector,
            team_access=team_access,
        )
        _write_connector_audit(
            team_access,
            action="connector.test",
            connector_id=connector.id,
            detail={
                "ok": ok,
                "model_listed": model_listed,
                "inference_ok": inference_ok,
                "status": public_connector.last_test_status.value,
            },
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)

    return ConnectorTestResponse(
        ok=ok,
        detail=detail,
        model_listed=model_listed,
        inference_ok=inference_ok,
        connector=public_connector,
    )


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
        _write_connector_audit(
            team_access,
            action="connector.activate",
            connector_id=connector.id,
            detail={"display_name": connector.display_name, "model_name": connector.model_name},
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)

    return ConnectorActivateResponse(
        detail="连接器已设为当前团队运行时。后续这个团队的任务上传、AI 解析和 MLZero 执行都会优先使用它。",
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
        _write_connector_audit(
            team_access,
            action="connector.deactivate",
            connector_id=connector.id,
            detail={"display_name": connector.display_name, "model_name": connector.model_name},
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)

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
        _write_connector_audit(
            team_access,
            action="connector.delete",
            connector_id=connector_id,
            detail={"display_name": connector.display_name, "was_active": connector.is_active},
        )
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)

    return ConnectorDeleteResponse(deleted=True, connector_id=connector_id, detail="连接器已删除。")
