from __future__ import annotations

from typing import Any
from urllib.parse import quote

from backend.app.core.config import Settings
from backend.app.core.secret_box import decrypt_secret, encrypt_secret, is_encrypted_secret
from backend.app.models.connector import (
    ConnectorCreateRequest,
    ConnectorTestStatus,
    ConnectorUpdateRequest,
    ConnectorWireApi,
    StoredConnectorRecord,
)
from backend.app.services.connector_http import ConnectorHttpClient, unwrap_single_record


class ConnectorStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = ConnectorHttpClient(settings)

    def list_connectors(self, team_id: str, *, access_token: str) -> list[StoredConnectorRecord]:
        payload = self._request_json(
            path=(
                "ai_connectors"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                "&order=created_at.desc"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected connector list response from Supabase.")
        return [self._connector_from_payload(item) for item in payload]

    def create_connector(
        self,
        payload: ConnectorCreateRequest,
        *,
        team_id: str,
        created_by: str,
        normalized_base_url: str,
        normalized_wire_api: ConnectorWireApi,
        access_token: str,
    ) -> StoredConnectorRecord:
        created_payload = self._request_json(
            path="ai_connectors",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "created_by": created_by,
                "display_name": payload.display_name.strip(),
                "provider_type": "openai-compatible",
                "endpoint_url": payload.endpoint_url.strip() if payload.endpoint_url else None,
                "base_url": normalized_base_url,
                "model_name": payload.model_name.strip(),
                "wire_api": normalized_wire_api.value,
                "api_key": self._encrypt_api_key(payload.api_key),
                "is_active": False,
            },
        )
        return self._connector_from_payload(unwrap_single_record(created_payload, "connector create"))

    def get_connector(self, team_id: str, connector_id: str, *, access_token: str) -> StoredConnectorRecord | None:
        payload = self._request_json(
            path=(
                "ai_connectors"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&id=eq.{quote(connector_id, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected connector detail response from Supabase.")
        if not payload:
            return None
        return self._connector_from_payload(payload[0])

    def get_active_connector(self, team_id: str, *, access_token: str) -> StoredConnectorRecord | None:
        payload = self._request_json(
            path=(
                "ai_connectors"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                "&is_active=eq.true"
                "&order=updated_at.desc"
                "&limit=1"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected active-connector response from Supabase.")
        if not payload:
            return None
        return self._connector_from_payload(payload[0])

    def save_connector(self, connector: StoredConnectorRecord, *, access_token: str) -> StoredConnectorRecord:
        updated_payload = self._request_json(
            path=(
                "ai_connectors"
                f"?team_id=eq.{quote(connector.team_id, safe='')}"
                f"&id=eq.{quote(connector.id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body={
                "display_name": connector.display_name,
                "provider_type": connector.provider_type,
                "endpoint_url": connector.endpoint_url,
                "base_url": connector.base_url,
                "model_name": connector.model_name,
                "wire_api": connector.wire_api.value,
                "api_key": self._encrypt_api_key(connector.api_key),
                "is_active": connector.is_active,
                "last_tested_at": connector.last_tested_at.isoformat() if connector.last_tested_at else None,
                "last_test_status": connector.last_test_status.value,
                "last_test_detail": connector.last_test_detail,
            },
        )
        return self._connector_from_payload(unwrap_single_record(updated_payload, "connector update"))

    def update_connector(
        self,
        connector: StoredConnectorRecord,
        payload: ConnectorUpdateRequest,
        *,
        normalized_base_url: str | None,
        normalized_wire_api: ConnectorWireApi | None,
        access_token: str,
    ) -> StoredConnectorRecord:
        if payload.display_name is not None:
            connector.display_name = payload.display_name.strip()
        if payload.endpoint_url is not None:
            connector.endpoint_url = payload.endpoint_url.strip() or None
        if normalized_base_url is not None:
            connector.base_url = normalized_base_url
        if payload.model_name is not None:
            connector.model_name = payload.model_name.strip()
        if normalized_wire_api is not None:
            connector.wire_api = normalized_wire_api
        if payload.api_key is not None:
            connector.api_key = payload.api_key.strip()
        connector.last_test_status = ConnectorTestStatus.untested
        connector.last_test_detail = "连接器配置已更新，需要重新测试。"
        connector.last_tested_at = None
        return self.save_connector(connector, access_token=access_token)

    def activate_connector(self, team_id: str, connector_id: str, *, access_token: str) -> StoredConnectorRecord:
        activated_payload = self._request_json(
            path="rpc/activate_ai_connector",
            access_token=access_token,
            method="POST",
            body={
                "target_team_id": team_id,
                "target_connector_id": connector_id,
            },
        )
        return self._connector_from_payload(unwrap_single_record(activated_payload, "connector activate"))

    def deactivate_connector(self, team_id: str, connector_id: str, *, access_token: str) -> StoredConnectorRecord:
        payload = self._request_json(
            path=(
                "ai_connectors"
                f"?team_id=eq.{quote(team_id, safe='')}"
                f"&id=eq.{quote(connector_id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body={"is_active": False},
        )
        return self._connector_from_payload(unwrap_single_record(payload, "connector deactivate"))

    def delete_connector(self, team_id: str, connector_id: str, *, access_token: str) -> bool:
        self._request_json(
            path=(
                "ai_connectors"
                f"?team_id=eq.{quote(team_id, safe='')}"
                f"&id=eq.{quote(connector_id, safe='')}"
            ),
            access_token=access_token,
            method="DELETE",
            expect_json=False,
        )
        return True

    def _connector_from_payload(self, payload: dict[str, Any]) -> StoredConnectorRecord:
        record = StoredConnectorRecord.model_validate(payload)
        if is_encrypted_secret(record.api_key):
            try:
                record.api_key = decrypt_secret(record.api_key, self.settings.connector_secret_key)
            except Exception as exc:
                raise RuntimeError("Could not decrypt stored connector API key. Check AI4ML_CONNECTOR_SECRET_KEY.") from exc
        return record

    def _encrypt_api_key(self, api_key: str) -> str:
        normalized = api_key.strip()
        if is_encrypted_secret(normalized):
            return normalized
        return encrypt_secret(normalized, self.settings.connector_secret_key)

    def _request_json(
        self,
        *,
        path: str,
        access_token: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        return self.http.request_json(
            path=path,
            access_token=access_token,
            method=method,
            body=body,
            expect_json=expect_json,
        )

    def _ensure_configured(self) -> None:
        self.http._ensure_configured()  # noqa: SLF001
