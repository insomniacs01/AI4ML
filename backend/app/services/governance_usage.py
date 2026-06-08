from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

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
from backend.app.services.governance_related_names import list_connector_names, list_task_names
from backend.app.services.governance_token_ledgers import normalize_ledger_limit, token_ledger_from_payload

RequestJson = Callable[..., Any]
ListMembers = Callable[..., list[TeamMemberRecord]]
ListProfiles = Callable[..., list[TeamProfileRecord]]

_QUOTA_SELECT = (
    "team_id,user_id,connector_id,scope_type,scope_key,token_quota,"
    "token_used,status,warning_threshold,updated_at"
)


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
            path=(
                "quota_accounts"
                f"?select={_QUOTA_SELECT}&team_id=eq.{quote(team_id, safe='')}"
            ),
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
        existing_row = self._existing_quota_row(
            team_id,
            access_token=access_token,
            filter_path=f"&user_id=eq.{quote(user_id, safe='')}",
        )
        row = self._write_quota_account(
            team_id,
            scope,
            token_quota=token_quota,
            status=status,
            warning_threshold=warning_threshold,
            existing_row=existing_row,
            update_filter=f"&user_id=eq.{quote(user_id, safe='')}",
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
        scope_filter = (
            f"&scope_type=eq.{quote(scope.scope_type, safe='')}"
            f"&scope_key=eq.{quote(scope.scope_key, safe='')}"
        )
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
        capped_limit = normalize_ledger_limit(limit)
        path = (
            "token_ledgers"
            f"?select=*&team_id=eq.{quote(team_id, safe='')}"
            f"&order=created_at.desc&limit={capped_limit}"
        )
        if user_id:
            path += f"&user_id=eq.{quote(user_id, safe='')}"
        if task_id:
            path += f"&task_id=eq.{quote(task_id, safe='')}"

        payload = self._request_json(path=path, access_token=access_token)
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected token-ledgers response from Supabase.")

        profile_map = {
            item.user_id: item
            for item in self._list_profiles(
                [str(item.get("user_id")) for item in payload if isinstance(item, dict) and item.get("user_id")],
                access_token=access_token,
            )
        }
        task_map = list_task_names(
            self._request_json,
            team_id,
            [str(item.get("task_id")) for item in payload if isinstance(item, dict) and item.get("task_id")],
            access_token=access_token,
        )
        connector_map = list_connector_names(
            self._request_json,
            team_id,
            [str(item.get("connector_id")) for item in payload if isinstance(item, dict) and item.get("connector_id")],
            access_token=access_token,
        )

        return [
            token_ledger_from_payload(
                item,
                profile_map=profile_map,
                task_map=task_map,
                connector_map=connector_map,
            )
            for item in payload
            if isinstance(item, dict)
        ]

    def _existing_quota_row(self, team_id: str, *, access_token: str, filter_path: str) -> dict[str, Any]:
        existing = self._request_json(
            path=(
                "quota_accounts"
                f"?select={_QUOTA_SELECT}&team_id=eq.{quote(team_id, safe='')}"
                f"{filter_path}&limit=1"
            ),
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
                path=(
                    "quota_accounts"
                    f"?team_id=eq.{quote(team_id, safe='')}{update_filter}"
                ),
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
            path=(
                "ai_connectors"
                f"?select=id,display_name&team_id=eq.{quote(team_id, safe='')}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            return {}
        return {
            str(item.get("id")): str(item.get("display_name"))
            for item in payload
            if isinstance(item, dict) and item.get("id")
        }
