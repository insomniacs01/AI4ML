from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from backend.app.services import task_routing


def _team_access() -> SimpleNamespace:
    return SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )


def test_runtime_context_maps_governance_permission_errors_to_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    class Store:
        def list_routing_policies(self, team_id: str, *, access_token: str) -> list[object]:
            raise PermissionError("governance denied")

    monkeypatch.setattr(task_routing, "get_governance_store", lambda: Store())

    with pytest.raises(HTTPException) as raised:
        task_routing._build_runtime_context(_team_access())

    assert raised.value.status_code == status.HTTP_403_FORBIDDEN
    assert raised.value.detail == "governance denied"
    assert raised.value.headers is None


def test_connector_resolution_maps_connector_permission_errors_to_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    class Store:
        def get_connector(self, team_id: str, connector_id: str, *, access_token: str) -> object:
            raise PermissionError("connector denied")

    monkeypatch.setattr(task_routing, "get_connector_store", lambda: Store())
    runtime_context = task_routing._RoutingRuntimeContext(team_policies={}, connector_cache={})

    with pytest.raises(HTTPException) as raised:
        task_routing._get_connector_by_id(_team_access(), runtime_context, "connector-1")

    assert raised.value.status_code == status.HTTP_403_FORBIDDEN
    assert raised.value.detail == "connector denied"
    assert raised.value.headers is None
