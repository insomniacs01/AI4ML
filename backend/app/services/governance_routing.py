from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from backend.app.models.governance import AIRoutingPoliciesUpdateRequest, AIRoutingPolicyRecord
from backend.app.services.governance_routing_policies import (
    connector_display_names,
    routing_policy_has_value,
    routing_policy_records_from_payload,
    routing_policy_stage,
    routing_policy_upsert_body,
)

RequestJson = Callable[..., Any]


class GovernanceRoutingRepository:
    _connector_display_names = staticmethod(connector_display_names)
    _routing_policy_records_from_payload = staticmethod(routing_policy_records_from_payload)
    _routing_policy_has_value = staticmethod(routing_policy_has_value)
    _routing_policy_stage = staticmethod(routing_policy_stage)
    _routing_policy_upsert_body = staticmethod(routing_policy_upsert_body)

    def __init__(self, *, request_json: RequestJson) -> None:
        self._request_json = request_json

    def list_routing_policies(self, team_id: str, *, access_token: str) -> list[AIRoutingPolicyRecord]:
        payload = self._request_json(
            path=(
                "ai_routing_policies"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}&order=stage.asc"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected routing-policy response from Supabase.")

        connector_payload = self._request_json(
            path=(
                "ai_connectors"
                f"?select=id,display_name&team_id=eq.{quote(team_id, safe='')}"
            ),
            access_token=access_token,
        )
        connector_map = self._connector_display_names(connector_payload)

        return self._routing_policy_records_from_payload(payload, connector_map=connector_map)

    def save_routing_policies(
        self,
        team_id: str,
        created_by: str,
        payload: AIRoutingPoliciesUpdateRequest,
        *,
        access_token: str,
    ) -> list[AIRoutingPolicyRecord]:
        for item in payload.items:
            stage = self._routing_policy_stage(item)
            if not self._routing_policy_has_value(item):
                self._request_json(
                    path=(
                        "ai_routing_policies"
                        f"?team_id=eq.{quote(team_id, safe='')}&stage=eq.{quote(stage, safe='')}"
                    ),
                    access_token=access_token,
                    method="DELETE",
                    expect_json=False,
                )
                continue
            self._request_json(
                path="ai_routing_policies?on_conflict=team_id,stage",
                access_token=access_token,
                method="POST",
                body=self._routing_policy_upsert_body(team_id, created_by, item),
                prefer="resolution=merge-duplicates,return=representation",
            )
        return self.list_routing_policies(team_id, access_token=access_token)
