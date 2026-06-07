from __future__ import annotations

import pytest
from fastapi import FastAPI

from backend.app.api.router import register_api_routes
from backend.app.core.config import Settings
from backend.app.models.governance import AIRoutingPoliciesUpdateRequest, AIRoutingPolicyUpsertRequest
from backend.app.services.team_routing_policy_validation import validate_routing_update


def test_validate_routing_update_rejects_model_without_connector() -> None:
    payload = AIRoutingPoliciesUpdateRequest(
        items=[
            AIRoutingPolicyUpsertRequest(
                stage="data_analysis",
                model_name="gpt-5",
            )
        ]
    )

    with pytest.raises(ValueError, match="connector_id"):
        validate_routing_update(payload)


def test_validate_routing_update_allows_connector_model_pair() -> None:
    payload = AIRoutingPoliciesUpdateRequest(
        items=[
            AIRoutingPolicyUpsertRequest(
                stage="data_analysis",
                connector_id="connector-1",
                model_name="gpt-5",
            )
        ]
    )

    validate_routing_update(payload)


def test_validate_routing_update_allows_empty_model_without_connector() -> None:
    payload = AIRoutingPoliciesUpdateRequest(
        items=[
            AIRoutingPolicyUpsertRequest(
                stage="data_analysis",
                model_name=" ",
            )
        ]
    )

    validate_routing_update(payload)


def test_team_routing_routes_remain_registered_under_team_prefix() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route_methods = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/api/teams/{team_id}/routing") in route_methods
    assert ("PUT", "/api/teams/{team_id}/routing") in route_methods
