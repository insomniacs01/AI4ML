from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.models.governance import TeamMemberRecord, TeamQuotaRecord
from backend.app.services.governance_payload_values import coerce_non_negative_int, optional_payload_str


@dataclass(frozen=True)
class ConnectorSummary:
    id: str
    display_name: str


@dataclass(frozen=True)
class QuotaScope:
    scope_type: str
    scope_key: str
    user_id: str | None
    connector_id: str | None


@dataclass(frozen=True)
class QuotaSubject:
    user_id: str | None = None
    connector_id: str | None = None
    role: str | None = None
    member_status: str | None = None
    display_name: str | None = None
    email: str | None = None
    connector_display_name: str | None = None


def quota_scope(scope_type: str, scope_key: str) -> QuotaScope:
    if scope_type == "member":
        return QuotaScope(scope_type=scope_type, scope_key=scope_key, user_id=scope_key, connector_id=None)
    if scope_type == "connector":
        return QuotaScope(scope_type=scope_type, scope_key=scope_key, user_id=None, connector_id=scope_key)
    return QuotaScope(scope_type=scope_type, scope_key=scope_key, user_id=None, connector_id=None)


def quota_map(payload: list[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        scope_type = str(item.get("scope_type") or "member")
        scope_key = str(item.get("scope_key") or item.get("user_id") or item.get("connector_id") or "")
        rows[(scope_type, scope_key)] = item
    return rows


def quota_record_from_payload(
    team_id: str,
    payload: dict[str, Any],
    *,
    member: TeamMemberRecord | None = None,
    connector: ConnectorSummary | None = None,
) -> TeamQuotaRecord:
    scope_type = quota_scope_type(payload, member=member, connector=connector)
    scope_key = quota_scope_key(team_id, payload, member=member, connector=connector)
    used = coerce_non_negative_int(payload.get("token_used"))
    resolved_quota = coerce_non_negative_int(payload.get("token_quota"))
    remaining = max(resolved_quota - used, 0)
    subject = quota_subject(payload, member=member, connector=connector)

    return TeamQuotaRecord(
        team_id=team_id,
        scope_type=scope_type,
        scope_key=scope_key,
        user_id=subject.user_id,
        connector_id=subject.connector_id,
        role=subject.role,
        member_status=subject.member_status,
        display_name=subject.display_name,
        email=subject.email,
        connector_display_name=subject.connector_display_name,
        token_quota=resolved_quota,
        token_used=used,
        token_remaining=remaining,
        status=quota_status(payload, resolved_quota, remaining),
        warning_threshold=coerce_non_negative_int(payload.get("warning_threshold")),
        updated_at=payload.get("updated_at"),
    )


def quota_scope_type(
    payload: dict[str, Any],
    *,
    member: TeamMemberRecord | None,
    connector: ConnectorSummary | None,
) -> str:
    if connector is not None:
        default_scope_type = "connector"
    elif member is not None:
        default_scope_type = "member"
    else:
        default_scope_type = "team"
    return str(payload.get("scope_type") or default_scope_type)


def quota_scope_key(
    team_id: str,
    payload: dict[str, Any],
    *,
    member: TeamMemberRecord | None,
    connector: ConnectorSummary | None,
) -> str:
    return str(
        payload.get("scope_key")
        or (member.user_id if member is not None else None)
        or (connector.id if connector is not None else None)
        or payload.get("user_id")
        or payload.get("connector_id")
        or team_id
    )


def quota_subject(
    payload: dict[str, Any],
    *,
    member: TeamMemberRecord | None,
    connector: ConnectorSummary | None,
) -> QuotaSubject:
    if member is not None:
        return QuotaSubject(
            user_id=member.user_id,
            role=member.role,
            member_status=member.member_status,
            display_name=member.profile.display_name if member.profile else None,
            email=member.profile.email if member.profile else None,
        )
    if connector is not None:
        return QuotaSubject(
            connector_id=connector.id,
            connector_display_name=connector.display_name,
        )
    return QuotaSubject(
        user_id=optional_payload_str(payload.get("user_id")),
        connector_id=optional_payload_str(payload.get("connector_id")),
        connector_display_name=optional_payload_str(payload.get("connector_display_name")),
    )


def quota_status(payload: dict[str, Any], resolved_quota: int, remaining: int) -> str:
    return str(payload.get("status") or ("exhausted" if resolved_quota and remaining == 0 else "active"))
