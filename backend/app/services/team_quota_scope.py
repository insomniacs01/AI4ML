from __future__ import annotations

from backend.app.models.governance import TeamQuotaScopeAdjustRequest


def resolve_quota_scope_key(payload: TeamQuotaScopeAdjustRequest, *, team_id: str) -> str | None:
    if payload.scope_type == "member":
        return payload.user_id or payload.scope_key
    if payload.scope_type == "connector":
        return payload.connector_id or payload.scope_key
    if payload.scope_type == "team":
        return payload.scope_key or team_id
    return payload.scope_key
