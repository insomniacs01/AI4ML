from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import (
    TeamAccessContext,
    require_team_access,
    require_team_owner_access,
)
from backend.app.models.governance import (
    TeamOwnershipTransferRequest,
    TeamOwnershipTransferResponse,
    TeamSettingsResponse,
    TeamSettingsUpdateRequest,
)
from backend.app.services.service_registry import get_governance_store


router = APIRouter(tags=["team"])



@router.get("/settings", response_model=TeamSettingsResponse)
def get_team_settings(team_access: TeamAccessContext = Depends(require_team_access)) -> TeamSettingsResponse:
    try:
        team = get_governance_store().get_team_settings(
            team_access.team_id,
            access_token=team_access.access_token,
        )
        if team is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="team not found")
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamSettingsResponse(team=team)


@router.patch("/settings", response_model=TeamSettingsResponse)
def update_team_settings(
    payload: TeamSettingsUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_owner_access),
) -> TeamSettingsResponse:
    store = get_governance_store()
    try:
        team = store.update_team_settings(
            team_access.team_id,
            payload,
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamSettingsResponse(team=team)


@router.post("/owner/transfer", response_model=TeamOwnershipTransferResponse)
def transfer_team_ownership(
    payload: TeamOwnershipTransferRequest,
    team_access: TeamAccessContext = Depends(require_team_owner_access),
) -> TeamOwnershipTransferResponse:
    store = get_governance_store()
    try:
        team, previous_owner, new_owner = store.transfer_ownership(
            team_access.team_id,
            current_owner_id=team_access.user.id,
            new_owner_user_id=payload.new_owner_user_id,
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamOwnershipTransferResponse(
        detail="团队所有权已转移。",
        team=team,
        previous_owner=previous_owner,
        new_owner=new_owner,
    )
