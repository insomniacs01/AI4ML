from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import TeamAccessContext, require_team_admin_access
from backend.app.models.governance import (
    TeamQuotaAdjustRequest,
    TeamQuotaAdjustResponse,
    TeamQuotaScopeAdjustRequest,
    TeamQuotasResponse,
    TokenLedgerRecord,
    TokenLedgersResponse,
)
from backend.app.services.service_registry import get_governance_store
from backend.app.services.team_quota_enforcement import pause_member_tasks_if_quota_exhausted
from backend.app.services.team_quota_scope import resolve_quota_scope_key


router = APIRouter(tags=["team"])


def token_ledger_totals(items: list[TokenLedgerRecord]) -> dict[str, int]:
    return {
        "total_tokens": sum(item.total_tokens for item in items),
        "input_tokens": sum(item.input_tokens for item in items),
        "output_tokens": sum(item.output_tokens for item in items),
    }



@router.get("/quotas", response_model=TeamQuotasResponse)
def list_team_quotas(team_access: TeamAccessContext = Depends(require_team_admin_access)) -> TeamQuotasResponse:
    try:
        items = get_governance_store().list_quotas(team_access.team_id, access_token=team_access.access_token)
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamQuotasResponse(team_id=team_access.team_id, items=items)


@router.post("/quotas/adjust", response_model=TeamQuotaAdjustResponse)
def adjust_team_quota_scope(
    payload: TeamQuotaScopeAdjustRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamQuotaAdjustResponse:
    scope_type = payload.scope_type
    scope_key = resolve_quota_scope_key(payload, team_id=team_access.team_id)
    if not scope_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="quota scope_key is required.")

    store = get_governance_store()
    try:
        quota = store.adjust_quota_scope(
            team_access.team_id,
            scope_type=scope_type,
            scope_key=scope_key,
            token_quota=payload.token_quota,
            status=payload.status,
            warning_threshold=payload.warning_threshold,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamQuotaAdjustResponse(detail="团队配额已更新。", quota=quota)


@router.post("/quotas/{member_id}/adjust", response_model=TeamQuotaAdjustResponse)
def adjust_team_quota(
    member_id: str,
    payload: TeamQuotaAdjustRequest,
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TeamQuotaAdjustResponse:
    store = get_governance_store()
    try:
        quota = store.adjust_quota(
            team_access.team_id,
            member_id,
            payload.token_quota,
            status=payload.status,
            warning_threshold=payload.warning_threshold,
            access_token=team_access.access_token,
        )
        pause_member_tasks_if_quota_exhausted(quota, member_id, team_access)
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TeamQuotaAdjustResponse(detail="成员配额已更新。", quota=quota)


@router.get("/token-ledgers", response_model=TokenLedgersResponse)
def list_team_token_ledgers(
    limit: int = Query(default=500, ge=1, le=1000),
    user_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    team_access: TeamAccessContext = Depends(require_team_admin_access),
) -> TokenLedgersResponse:
    try:
        items = get_governance_store().list_token_ledgers(
            team_access.team_id,
            access_token=team_access.access_token,
            limit=limit,
            user_id=user_id,
            task_id=task_id,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)
    return TokenLedgersResponse(
        team_id=team_access.team_id,
        items=items,
        **token_ledger_totals(items),
    )
