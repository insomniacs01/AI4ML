from __future__ import annotations

from datetime import datetime, timezone

from backend.app.core.config import get_settings
from backend.app.models.connector import (
    ConnectorTestResponse,
    ConnectorTestStatus,
    StoredConnectorRecord,
)
from backend.app.services.connector_runtime import probe_provider
from backend.app.services.connector_store import ConnectorStore


def probe_and_save_connector(
    connector_store: ConnectorStore,
    connector: StoredConnectorRecord,
    *,
    access_token: str,
) -> ConnectorTestResponse:
    settings = get_settings()
    result = probe_provider(
        base_url=connector.base_url,
        api_key=connector.api_key,
        model_name=connector.model_name,
        wire_api=connector.wire_api,
        timeout_seconds=settings.ai_provider_request_timeout_seconds,
        user_agent=settings.ai_provider_user_agent,
    )
    connector.last_test_status = ConnectorTestStatus.passed if result.ok else ConnectorTestStatus.failed
    connector.last_test_detail = result.detail
    connector.last_tested_at = datetime.now(timezone.utc)
    saved_connector = connector_store.save_connector(connector, access_token=access_token)
    return ConnectorTestResponse(
        ok=result.ok,
        detail=result.detail,
        model_listed=result.model_listed,
        inference_ok=result.inference_ok,
        connector=saved_connector.to_public(),
    )


def probe_and_save_connectors(
    connector_store: ConnectorStore,
    *,
    team_id: str,
    access_token: str,
) -> list[ConnectorTestResponse]:
    return [
        probe_and_save_connector(connector_store, connector, access_token=access_token)
        for connector in connector_store.list_connectors(team_id, access_token=access_token)
    ]
