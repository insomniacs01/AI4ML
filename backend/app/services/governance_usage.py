from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.models.governance import (
    TeamMemberRecord,
    TeamProfileRecord,
    TeamQuotaRecord,
    TokenLedgerRecord,
)
from backend.app.services.governance_http import unwrap_single_record
from backend.app.services.governance_quota_records import (
    QuotaScope,
    quota_record_from_payload,
    quota_scope,
)
from backend.app.services.governance_quota_listing import build_quota_records
from backend.app.services.governance_quota_writes import build_quota_account_payload
from backend.app.services.governance_token_ledger_listing import list_token_ledger_records
from backend.app.services.governance_usage_queries import (
    connector_names_path,
    member_quota_filter,
    quota_accounts_path,
    quota_existing_path,
    quota_update_path,
    scope_quota_filter,
)

RequestJson = Callable[..., Any]
ListMembers = Callable[..., list[TeamMemberRecord]]
ListProfiles = Callable[..., list[TeamProfileRecord]]

class GovernanceUsageRepository:
    def __init__(
        self,
        *,
        request_json: RequestJson,
        list_members: ListMembers,
        list_profiles: ListProfiles,
    ) -> None:
        self._request_json = request_json
        self._list_members = list_members
        self._list_profiles = list_profiles

    def list_quotas(self, team_id: str, *, access_token: str) -> list[TeamQuotaRecord]:
        members = self._list_members(team_id, access_token=access_token)
        quota_payload = self._request_json(
            path=quota_accounts_path(team_id),
            access_token=access_token,
        )
        if not isinstance(quota_payload, list):
            raise ConnectionError("Unexpected quota response from Supabase.")

        connector_map = self._connector_map(team_id, access_token=access_token)
        return build_quota_records(
            team_id,
            members=members,
            connector_map=connector_map,
            quota_payload=quota_payload,
        )

    def adjust_quota(
        self,
        team_id: str,
        user_id: str,
        token_quota: int | None,
        *,
        status: str | None = None,
        warning_threshold: int | None = None,
        access_token: str,
    ) -> TeamQuotaRecord:
        scope = quota_scope("member", user_id)
        filter_path = member_quota_filter(user_id)
        existing_row = self._existing_quota_row(
            team_id,
            access_token=access_token,
            filter_path=filter_path,
        )
        row = self._write_quota_account(
            team_id,
            scope,
            token_quota=token_quota,
            status=status,
            warning_threshold=warning_threshold,
            existing_row=existing_row,
            update_filter=filter_path,
            access_token=access_token,
            action="quota adjust",
        )
        member = next(
            (item for item in self._list_members(team_id, access_token=access_token) if item.user_id == user_id),
            None,
        )
        return quota_record_from_payload(team_id, row, member=member)

    def adjust_quota_scope(
        self,
        team_id: str,
        *,
        scope_type: str,
        scope_key: str,
        token_quota: int | None,
        status: str | None = None,
        warning_threshold: int | None = None,
        access_token: str,
    ) -> TeamQuotaRecord:
        scope = quota_scope(scope_type, scope_key)
        scope_filter = scope_quota_filter(scope.scope_type, scope.scope_key)
        row = self._write_quota_account(
            team_id,
            scope,
            token_quota=token_quota,
            status=status,
            warning_threshold=warning_threshold,
            existing_row=self._existing_quota_row(
                team_id,
                access_token=access_token,
                filter_path=scope_filter,
            ),
            update_filter=scope_filter,
            access_token=access_token,
            action="quota scope adjust",
        )
        return quota_record_from_payload(team_id, row)

    def get_member_quota(self, team_id: str, user_id: str, *, access_token: str) -> TeamQuotaRecord | None:
        items = self.list_quotas(team_id, access_token=access_token)
        return next((item for item in items if item.user_id == user_id), None)

    def list_token_ledgers(
        self,
        team_id: str,
        *,
        access_token: str,
        limit: int = 500,
        user_id: str | None = None,
        task_id: str | None = None,
    ) -> list[TokenLedgerRecord]:
        return list_token_ledger_records(
            self._request_json,
            self._list_profiles,
            team_id,
            access_token=access_token,
            limit=limit,
            user_id=user_id,
            task_id=task_id,
        )

    def _existing_quota_row(self, team_id: str, *, access_token: str, filter_path: str) -> dict[str, Any]:
        existing = self._request_json(
            path=quota_existing_path(team_id, filter_path),
            access_token=access_token,
        )
        return existing[0] if isinstance(existing, list) and existing else {}

    def _write_quota_account(
        self,
        team_id: str,
        scope: QuotaScope,
        *,
        token_quota: int | None,
        status: str | None,
        warning_threshold: int | None,
        existing_row: dict[str, Any],
        update_filter: str,
        access_token: str,
        action: str,
    ) -> dict[str, Any]:
        payload = build_quota_account_payload(
            team_id,
            scope,
            token_quota=token_quota,
            status=status,
            warning_threshold=warning_threshold,
            existing_row=existing_row,
        )
        if existing_row:
            updated = self._request_json(
                path=quota_update_path(team_id, update_filter),
                access_token=access_token,
                method="PATCH",
                body=payload,
            )
        else:
            updated = self._request_json(
                path="quota_accounts",
                access_token=access_token,
                method="POST",
                body=payload,
            )
        return unwrap_single_record(updated, action)

    def _connector_map(self, team_id: str, *, access_token: str) -> dict[str, str]:
        payload = self._request_json(
            path=connector_names_path(team_id),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            return {}
        return {
            str(item.get("id")): str(item.get("display_name"))
            for item in payload
            if isinstance(item, dict) and item.get("id")
        }
