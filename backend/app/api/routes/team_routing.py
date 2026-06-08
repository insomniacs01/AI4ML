from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_admin_access
from backend.app.models.governance import (
    AIRoutingPoliciesResponse,
    AIRoutingPoliciesUpdateRequest,
    AIRoutingPoliciesUpdateResponse,
)
from backend.app.services.service_registry import get_governance_store
from backend.app.services.team_routing_policy_validation import validate_routing_update


router = APIRouter(tags=["team"])



@router.get("/routing", response_model=AIRoutingPoliciesResponse)
def list_team_routing(team_access: TeamAccessContext = Depends(require_team_access)) -> AIRoutingPoliciesResponse:
    try:
        items = get_governance_store().list_routing_policies(
            team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return AIRoutingPoliciesResponse(team_id=team_access.team_id, items=items)


@router.put("/routing", response_model=AIRoutingPoliciesUpdateResponse)
def save_team_routing(
    payload: AIRoutingPoliciesUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> AIRoutingPoliciesUpdateResponse:
    try:
        validate_routing_update(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    store = get_governance_store()
    try:
        items = store.save_routing_policies(
            team_access.team_id,
            team_access.user.id,
            payload,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return AIRoutingPoliciesUpdateResponse(
        detail="默认 AI 路由已更新。",
        team_id=team_access.team_id,
        items=items,
    )
