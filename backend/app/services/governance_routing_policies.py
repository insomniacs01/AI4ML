from __future__ import annotations

from typing import Any

from backend.app.models.governance import AIRoutingPolicyRecord, AIRoutingPolicyUpsertRequest
from backend.app.services.governance_payload_values import optional_payload_str


def connector_display_names(payload: Any) -> dict[str, str]:
    if not isinstance(payload, list):
        return {}
    return {
        str(item.get("id")): str(item.get("display_name"))
        for item in payload
        if isinstance(item, dict) and item.get("id")
    }


def routing_policy_records_from_payload(
    payload: list[Any],
    *,
    connector_map: dict[str, str],
) -> list[AIRoutingPolicyRecord]:
    return [
        routing_policy_record_from_payload(item, connector_map=connector_map)
        for item in payload
        if isinstance(item, dict)
    ]


def routing_policy_record_from_payload(
    payload: dict[str, Any],
    *,
    connector_map: dict[str, str],
) -> AIRoutingPolicyRecord:
    connector_id = optional_payload_str(payload.get("connector_id"))
    return AIRoutingPolicyRecord(
        id=optional_payload_str(payload.get("id")),
        team_id=str(payload.get("team_id")),
        stage=str(payload.get("stage")),
        connector_id=connector_id,
        connector_display_name=connector_map.get(connector_id) if connector_id else None,
        model_name=optional_payload_str(payload.get("model_name")),
        config=payload.get("config") if isinstance(payload.get("config"), dict) else None,
        created_by=optional_payload_str(payload.get("created_by")),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
    )


def routing_policy_stage(item: AIRoutingPolicyUpsertRequest) -> str:
    return item.stage.strip()


def routing_policy_has_value(item: AIRoutingPolicyUpsertRequest) -> bool:
    return bool(item.connector_id or item.model_name or item.config)


def routing_policy_upsert_body(
    team_id: str,
    created_by: str,
    item: AIRoutingPolicyUpsertRequest,
) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "stage": routing_policy_stage(item),
        "connector_id": item.connector_id,
        "model_name": item.model_name,
        "config": item.config,
        "created_by": created_by,
    }
