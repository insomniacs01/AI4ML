from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.governance import AIRoutingPolicyUpsertRequest
from backend.app.services.governance_routing_policies import (
    connector_display_names,
    routing_policy_has_value,
    routing_policy_records_from_payload,
    routing_policy_stage,
    routing_policy_upsert_body,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_connector_display_names_filters_invalid_rows() -> None:
    names = connector_display_names(
        [
            {"id": "connector-1", "display_name": "Connector One"},
            {"display_name": "missing id"},
            "not-a-row",
        ]
    )

    assert names == {"connector-1": "Connector One"}
    assert connector_display_names({"id": "not-a-list"}) == {}


def test_routing_policy_records_from_payload_enriches_connector_names_and_skips_invalid_rows() -> None:
    records = routing_policy_records_from_payload(
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
            },
            {
                "team_id": "team-1",
                "stage": "model_training",
                "connector_id": "connector-missing",
                "config": "not-a-dict",
            },
            "not-a-row",
        ],
        connector_map={"connector-1": "Connector One"},
    )

    assert len(records) == 2
    assert records[0].id == "policy-1"
    assert records[0].connector_display_name == "Connector One"
    assert records[0].model_name == "gpt-5"
    assert records[0].config == {"temperature": 0}
    assert records[0].created_at == NOW
    assert records[0].updated_at == NOW
    assert records[1].connector_display_name is None
    assert records[1].config is None


def test_routing_policy_stage_and_value_rules_match_store_write_rules() -> None:
    empty_item = AIRoutingPolicyUpsertRequest(stage=" data_analysis ")
    connector_item = AIRoutingPolicyUpsertRequest(stage="model_training", connector_id="connector-1")
    model_item = AIRoutingPolicyUpsertRequest(stage="reporting", model_name=" ")
    config_item = AIRoutingPolicyUpsertRequest(stage="review", config={"top_p": 1})

    assert routing_policy_stage(empty_item) == "data_analysis"
    assert not routing_policy_has_value(empty_item)
    assert routing_policy_has_value(connector_item)
    assert routing_policy_has_value(model_item)
    assert routing_policy_has_value(config_item)


def test_routing_policy_upsert_body_uses_trimmed_stage_and_preserves_payload_values() -> None:
    item = AIRoutingPolicyUpsertRequest(
        stage=" data_analysis ",
        connector_id="connector-1",
        model_name="gpt-5",
        config={"temperature": 0},
    )

    assert routing_policy_upsert_body("team-1", "owner-1", item) == {
        "team_id": "team-1",
        "stage": "data_analysis",
        "connector_id": "connector-1",
        "model_name": "gpt-5",
        "config": {"temperature": 0},
        "created_by": "owner-1",
    }
