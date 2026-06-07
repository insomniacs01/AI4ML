from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import TeamAccessContext, require_team_admin_access
from backend.app.models.governance import (
    AdminPasswordResetRequest,
    AdminPasswordResetResponse,
    AdminUserUpdateRequest,
    AdminUserUpdateResponse,
    PlatformLimitsRecord,
    PlatformLimitsResponse,
)
from backend.app.services.admin_user_management import (
    AdminUserManagementError,
    reset_supabase_user_password,
)
from backend.app.services.platform_limits import read_platform_limits, save_platform_limits
from backend.app.services.service_registry import get_governance_store
from backend.app.services.team_admin_user_update import (
    AdminRoleUpdateBlockedError,
    AdminTargetMemberNotFoundError,
    update_admin_user_record,
)
from backend.app.services.team_quota_enforcement import pause_member_tasks_if_quota_exhausted


router = APIRouter(tags=["team"])


def _raise_governance_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    raise_store_http_error(exc)


@router.put("/admin/users/{member_id}", response_model=AdminUserUpdateResponse)
def update_admin_user(
    member_id: str,
    payload: AdminUserUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> AdminUserUpdateResponse:
    store = get_governance_store()
    try:
        result = update_admin_user_record(
            store,
            team_id=team_access.team_id,
            member_id=member_id,
            payload=payload,
            access_token=team_access.access_token,
        )
        pause_member_tasks_if_quota_exhausted(result.quota, member_id, team_access)
    except AdminTargetMemberNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AdminRoleUpdateBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except AdminUserManagementError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return AdminUserUpdateResponse(detail="用户权限与额度已更新。", member=result.member, quota=result.quota)


@router.post("/admin/users/{member_id}/reset-password", response_model=AdminPasswordResetResponse)
def reset_admin_user_password(
    member_id: str,
    payload: AdminPasswordResetRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> AdminPasswordResetResponse:
    try:
        reset_supabase_user_password(get_governance_store().settings, user_id=member_id, password=payload.password)
    except AdminUserManagementError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return AdminPasswordResetResponse(detail="用户密码已重置。", user_id=member_id)


@router.get("/admin/platform-limits", response_model=PlatformLimitsResponse)
def get_admin_platform_limits(
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> PlatformLimitsResponse:
    return PlatformLimitsResponse(**read_platform_limits(get_governance_store().settings).model_dump())


@router.put("/admin/platform-limits", response_model=PlatformLimitsResponse)
def update_admin_platform_limits(
    payload: PlatformLimitsRecord,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> PlatformLimitsResponse:
    limits = save_platform_limits(get_governance_store().settings, payload)
    return PlatformLimitsResponse(**limits.model_dump())
