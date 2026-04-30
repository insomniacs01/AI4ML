from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.app.core.config import Settings
from backend.app.models.connector import ConnectorCreateRequest, ConnectorWireApi, StoredConnectorRecord


class ConnectorStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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
        return [StoredConnectorRecord.model_validate(item) for item in payload]

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
                "api_key": payload.api_key.strip(),
                "is_active": False,
            },
        )
        return StoredConnectorRecord.model_validate(self._unwrap_single_record(created_payload, "connector create"))

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
        return StoredConnectorRecord.model_validate(payload[0])

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
        return StoredConnectorRecord.model_validate(payload[0])

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
                "api_key": connector.api_key,
                "is_active": connector.is_active,
                "last_tested_at": connector.last_tested_at.isoformat() if connector.last_tested_at else None,
                "last_test_status": connector.last_test_status.value,
                "last_test_detail": connector.last_test_detail,
            },
        )
        return StoredConnectorRecord.model_validate(self._unwrap_single_record(updated_payload, "connector update"))

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
        return StoredConnectorRecord.model_validate(self._unwrap_single_record(activated_payload, "connector activate"))

    def _request_json(
        self,
        *,
        path: str,
        access_token: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> Any:
        self._ensure_configured()

        url = f"{self.settings.supabase_rest_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "apikey": self.settings.supabase_publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept-Profile": "public",
            "Content-Profile": "public",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Prefer"] = "return=representation"
            data = json.dumps(body).encode("utf-8")

        request = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.settings.supabase_timeout_seconds) as response:  # noqa: S310
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            if exc.code in (401, 403):
                raise PermissionError("Supabase rejected the connector storage request.") from exc
            if "ai_connectors" in payload and "does not exist" in payload:
                raise RuntimeError(
                    "Supabase ai_connectors schema is missing. "
                    "Apply supabase/schema.sql before using connector storage."
                ) from exc
            if "activate_ai_connector" in payload and "Could not find the function" in payload:
                raise RuntimeError(
                    "Supabase activate_ai_connector RPC is missing. "
                    "Apply supabase/schema.sql before using connector activation."
                ) from exc
            raise ConnectionError(
                f"Supabase connector request failed with HTTP {exc.code}. Response: {payload or '<empty>'}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ConnectionError("Could not reach Supabase to read or write connector records.") from exc

        if not raw_body:
            return None

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ConnectionError("Supabase connector response was not valid JSON.") from exc

    def _ensure_configured(self) -> None:
        if self.settings.supabase_configured:
            return
        raise RuntimeError(
            "Supabase connector storage is not configured. "
            "Set AI4ML_SUPABASE_URL / AI4ML_SUPABASE_PUBLISHABLE_KEY or keep frontend/.env.local available."
        )

    @staticmethod
    def _unwrap_single_record(payload: Any, action: str) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        raise ConnectionError(f"Unexpected Supabase response shape during {action}.")
