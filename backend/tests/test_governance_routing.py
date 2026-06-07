from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.app.models.governance import AIRoutingPoliciesUpdateRequest, AIRoutingPolicyUpsertRequest
from backend.app.services.governance_routing import GovernanceRoutingRepository


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class RequestRecorder:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError(f"unexpected request: {kwargs}")
        return self.responses.pop(0)


def _repository(responses: list[Any]) -> tuple[GovernanceRoutingRepository, RequestRecorder]:
    request = RequestRecorder(responses)
    return GovernanceRoutingRepository(request_json=request), request


def test_list_routing_policies_fetches_policies_and_connector_names() -> None:
    repository, request = _repository(
        [
            [
                {
                    "id": "policy-1",
                    "team_id": "team-1",
                    "stage": "data_analysis",
                    "connector_id": "connector-1",
                    "model_name": "gpt-5",
                    "config": {"temperature": 0},
                    "created_by": "owner-1",
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            ],
            [{"id": "connector-1", "display_name": "Connector One"}],
        ]
    )

    records = repository.list_routing_policies("team-1", access_token="token")

    assert len(records) == 1
    assert records[0].stage == "data_analysis"
    assert records[0].connector_display_name == "Connector One"
    assert records[0].created_at == NOW
    assert request.calls[0]["path"] == "ai_routing_policies?select=*&team_id=eq.team-1&order=stage.asc"
    assert request.calls[1]["path"] == "ai_connectors?select=id,display_name&team_id=eq.team-1"


def test_list_routing_policies_rejects_unexpected_policy_payload() -> None:
    repository, _ = _repository([{"not": "a-list"}])

    with pytest.raises(ConnectionError, match="routing-policy response"):
        repository.list_routing_policies("team-1", access_token="token")


def test_save_routing_policies_deletes_empty_items_upserts_values_and_returns_current_list() -> None:
    repository, request = _repository(
        [
            None,
            [{"id": "upserted"}],
            [
                {
                    "id": "policy-1",
                    "team_id": "team-1",
                    "stage": "model_training",
                    "connector_id": "connector-1",
                    "model_name": "gpt-5",
                }
            ],
            [{"id": "connector-1", "display_name": "Connector One"}],
        ]
    )

    records = repository.save_routing_policies(
        "team-1",
        "owner-1",
        AIRoutingPoliciesUpdateRequest(
            items=[
                AIRoutingPolicyUpsertRequest(stage=" data_analysis "),
                AIRoutingPolicyUpsertRequest(
                    stage=" model_training ",
                    connector_id="connector-1",
                    model_name="gpt-5",
                    config={"temperature": 0},
                ),
            ]
        ),
        access_token="token",
    )

    assert records[0].stage == "model_training"
    assert records[0].connector_display_name == "Connector One"
    assert request.calls[0] == {
        "path": "ai_routing_policies?team_id=eq.team-1&stage=eq.data_analysis",
        "access_token": "token",
        "method": "DELETE",
        "expect_json": False,
    }
    assert request.calls[1]["path"] == "ai_routing_policies?on_conflict=team_id,stage"
    assert request.calls[1]["method"] == "POST"
    assert request.calls[1]["body"] == {
        "team_id": "team-1",
        "stage": "model_training",
        "connector_id": "connector-1",
        "model_name": "gpt-5",
        "config": {"temperature": 0},
        "created_by": "owner-1",
    }
    assert request.calls[1]["prefer"] == "resolution=merge-duplicates,return=representation"
    assert request.calls[2]["path"] == "ai_routing_policies?select=*&team_id=eq.team-1&order=stage.asc"
    assert request.calls[3]["path"] == "ai_connectors?select=id,display_name&team_id=eq.team-1"
