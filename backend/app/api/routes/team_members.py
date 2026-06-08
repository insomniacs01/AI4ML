from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_admin_access
from backend.app.models.governance import (
    TeamInviteRequest,
    TeamInviteResponse,
    TeamMemberRoleUpdateRequest,
    TeamMemberRoleUpdateResponse,
    TeamMembersResponse,
    TeamMemberStatusUpdateRequest,
    TeamMemberStatusUpdateResponse,
)
from backend.app.services.service_registry import get_governance_store
from backend.app.services.team_invite import build_team_invite_response
from backend.app.services.team_member_role_rules import assert_member_role_update_allowed


router = APIRouter(tags=["team"])



@router.get("/members", response_model=TeamMembersResponse)
def list_team_members(team_access: TeamAccessContext = Depends(require_team_access)) -> TeamMembersResponse:
    try:
        items = get_governance_store().list_members(team_access.team_id, access_token=team_access.access_token)
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamMembersResponse(team_id=team_access.team_id, items=items)


@router.post("/members/invite", response_model=TeamInviteResponse)
def get_team_invite_details(
    payload: TeamInviteRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamInviteResponse:
    store = get_governance_store()
    try:
        team = store.get_team(team_access.team_id, access_token=team_access.access_token)
        if team is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="team not found")
    except HTTPException:
        raise
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

    return build_team_invite_response(
        team_id=team_access.team_id,
        team=team,
        email=payload.email,
    )


@router.patch("/members/{member_id}/role", response_model=TeamMemberRoleUpdateResponse)
def update_team_member_role(
    member_id: str,
    payload: TeamMemberRoleUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamMemberRoleUpdateResponse:
    try:
        assert_member_role_update_allowed(
            target_member_id=member_id,
            requested_role=payload.role,
            actor_user_id=team_access.user.id,
            actor_role=team_access.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    store = get_governance_store()
    try:
        member = store.update_member_role(
            team_access.team_id,
            member_id,
            payload.role,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamMemberRoleUpdateResponse(detail="成员角色已更新。", member=member)


@router.patch("/members/{member_id}/status", response_model=TeamMemberStatusUpdateResponse)
def update_team_member_status(
    member_id: str,
    payload: TeamMemberStatusUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamMemberStatusUpdateResponse:
    store = get_governance_store()
    try:
        member = store.update_member_status(
            team_access.team_id,
            member_id,
            payload.member_status,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamMemberStatusUpdateResponse(detail="成员状态已更新。", member=member)
