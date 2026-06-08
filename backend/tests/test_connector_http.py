from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.services.connector_http import ConnectorHttpClient, unwrap_single_record


def test_connector_http_rejects_missing_supabase_config() -> None:
    client = ConnectorHttpClient(Settings(_env_file=None, supabase_url="", supabase_publishable_key=""))

    try:
        client.request_json(path="ai_connectors", access_token="token")
    except RuntimeError as exc:
        assert "Supabase connector storage is not configured" in str(exc)
    else:
        raise AssertionError("missing Supabase config should raise RuntimeError")


def test_unwrap_single_record_accepts_dict_and_one_item_list() -> None:
    assert unwrap_single_record({"id": "connector-1"}, "connector read") == {"id": "connector-1"}
    assert unwrap_single_record([{"id": "connector-1"}], "connector read") == {"id": "connector-1"}


def test_unwrap_single_record_rejects_unexpected_shape() -> None:
    try:
        unwrap_single_record([], "connector read")
    except ConnectionError as exc:
        assert "Unexpected Supabase response shape during connector read" in str(exc)
    else:
        raise AssertionError("empty Supabase response should raise ConnectionError")
