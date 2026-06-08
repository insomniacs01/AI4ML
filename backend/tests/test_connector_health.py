from __future__ import annotations

from datetime import datetime, timezone

from backend.app.core.config import Settings
from backend.app.models.connector import ConnectorTestStatus, ConnectorWireApi, StoredConnectorRecord
from backend.app.services import connector_health
from backend.app.services.connector_runtime import ProviderProbeResult


class _FakeConnectorStore:
    def __init__(self, connectors: list[StoredConnectorRecord]) -> None:
        self.connectors = connectors
        self.saved: list[StoredConnectorRecord] = []
        self.list_calls: list[dict] = []

    def save_connector(self, connector: StoredConnectorRecord, *, access_token: str) -> StoredConnectorRecord:
        self.saved.append(connector)
        return connector

    def list_connectors(self, team_id: str, *, access_token: str) -> list[StoredConnectorRecord]:
        self.list_calls.append({"team_id": team_id, "access_token": access_token})
        return self.connectors


def test_probe_and_save_connector_records_success(monkeypatch) -> None:
    connector = _connector()
    store = _FakeConnectorStore([connector])
    calls: list[dict] = []

    def fake_probe_provider(**kwargs) -> ProviderProbeResult:
        calls.append(kwargs)
        return ProviderProbeResult(ok=True, detail="ok", model_listed=True, inference_ok=True)

    monkeypatch.setattr(connector_health, "get_settings", lambda: Settings(ai_provider_request_timeout_seconds=7, ai_provider_user_agent="Test UA"))
    monkeypatch.setattr(connector_health, "probe_provider", fake_probe_provider)

    response = connector_health.probe_and_save_connector(store, connector, access_token="token-1")

    assert calls == [
        {
            "base_url": "https://example.test/v1",
            "api_key": "secret-key",
            "model_name": "model-a",
            "wire_api": ConnectorWireApi.chat_completions,
            "timeout_seconds": 7,
            "user_agent": "Test UA",
        }
    ]
    assert store.saved[0].last_test_status == ConnectorTestStatus.passed
    assert store.saved[0].last_test_detail == "ok"
    assert store.saved[0].last_tested_at is not None
    assert response.ok is True
    assert response.connector.api_key_masked == "secr...-key"


def test_probe_and_save_connectors_lists_team_connectors(monkeypatch) -> None:
    connector = _connector()
    store = _FakeConnectorStore([connector])

    def fake_probe_provider(**kwargs) -> ProviderProbeResult:
        return ProviderProbeResult(ok=False, detail="failed", model_listed=False, inference_ok=False)

    monkeypatch.setattr(connector_health, "probe_provider", fake_probe_provider)

    responses = connector_health.probe_and_save_connectors(store, team_id="team-1", access_token="token-1")

    assert store.list_calls == [{"team_id": "team-1", "access_token": "token-1"}]
    assert responses[0].ok is False
    assert store.saved[0].last_test_status == ConnectorTestStatus.failed
    assert store.saved[0].last_test_detail == "failed"


def _connector() -> StoredConnectorRecord:
    now = datetime.now(timezone.utc)
    return StoredConnectorRecord(
        id="connector-1",
        team_id="team-1",
        created_by="user-1",
        display_name="Connector One",
        base_url="https://example.test/v1",
        model_name="model-a",
        wire_api=ConnectorWireApi.chat_completions,
        api_key="secret-key",
        created_at=now,
        updated_at=now,
    )
