from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_admin_access
from backend.app.models.connector import (
    ConnectorActivateResponse,
    ConnectorCreateRequest,
    ConnectorListResponse,
    ConnectorRecord,
    ConnectorTestStatus,
    ConnectorTestResponse,
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
        _write_connector_audit(
            team_access,
            action="connector.test",
            connector_id=connector.id,
            detail={
                "ok": result.ok,
                "model_listed": result.model_listed,
                "inference_ok": result.inference_ok,
                "status": connector.last_test_status.value,
            },
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)

    return ConnectorTestResponse(
        ok=result.ok,
        detail=result.detail,
        model_listed=result.model_listed,
        inference_ok=result.inference_ok,
        connector=connector.to_public(),
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
