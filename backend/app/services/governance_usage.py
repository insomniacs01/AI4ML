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
from backend.app.services.governance_quota_records import (
    ConnectorSummary,
    QuotaScope,
    coerce_non_negative_int,
    quota_map,
    quota_record_from_payload,
    quota_scope,
)

RequestJson = Callable[..., Any]
ListMembers = Callable[..., list[TeamMemberRecord]]
ListProfiles = Callable[..., list[TeamProfileRecord]]

_QUOTA_SELECT = (
    "team_id,user_id,connector_id,scope_type,scope_key,token_quota,"
    "token_used,status,warning_threshold,updated_at"
)


class GovernanceUsageRepository:
    _quota_map = staticmethod(quota_map)
    _quota_record_from_payload = staticmethod(quota_record_from_payload)

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
        quota_rows = self._quota_map(quota_payload)

        items: list[TeamQuotaRecord] = []
        handled_keys: set[tuple[str, str]] = set()

        for member in members:
            key = ("member", member.user_id)
            items.append(self._quota_record_from_payload(team_id, quota_rows.get(key, {}), member=member))
            handled_keys.add(key)

        for connector_id, connector_name in connector_map.items():
            key = ("connector", connector_id)
            items.append(
                self._quota_record_from_payload(
                    team_id,
                    quota_rows.get(key, {}),
                    connector=ConnectorSummary(id=connector_id, display_name=connector_name),
                )
            )
            handled_keys.add(key)

        team_key = ("team", team_id)
        items.append(self._quota_record_from_payload(team_id, quota_rows.get(team_key, {})))
        handled_keys.add(team_key)

        for key, quota_row in quota_rows.items():
            if key not in handled_keys:
                items.append(self._quota_record_from_payload(team_id, quota_row))
        return items

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
        return self._quota_record_from_payload(team_id, row, member=member)

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
        return self._quota_record_from_payload(team_id, row)

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
        capped_limit = min(max(limit, 1), 1000)
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
        task_map = self._list_task_names(
            team_id,
            [str(item.get("task_id")) for item in payload if isinstance(item, dict) and item.get("task_id")],
            access_token=access_token,
        )
        connector_map = self._list_connector_names(
            team_id,
            [str(item.get("connector_id")) for item in payload if isinstance(item, dict) and item.get("connector_id")],
            access_token=access_token,
        )

        return [
            self._token_ledger_from_payload(
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
        resolved_token_quota = (
            token_quota
            if token_quota is not None
            else coerce_non_negative_int(existing_row.get("token_quota"))
        )
        resolved_status = status or str(existing_row.get("status") or "active")
        if (
            status is None
            and token_quota is not None
            and resolved_status == "exhausted"
            and resolved_token_quota > coerce_non_negative_int(existing_row.get("token_used"))
        ):
            resolved_status = "active"
        payload = {
            "team_id": team_id,
            "user_id": scope.user_id,
            "connector_id": scope.connector_id,
            "scope_type": scope.scope_type,
            "scope_key": scope.scope_key,
            "token_quota": resolved_token_quota,
            "status": resolved_status,
            "warning_threshold": (
                warning_threshold
                if warning_threshold is not None
                else coerce_non_negative_int(existing_row.get("warning_threshold"))
            ),
        }
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
        return _unwrap_single_record(updated, action)

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

    def _token_ledger_from_payload(
        self,
        payload: dict[str, Any],
        *,
        profile_map: dict[str, TeamProfileRecord],
        task_map: dict[str, str],
        connector_map: dict[str, str],
    ) -> TokenLedgerRecord:
        ledger_user_id = str(payload.get("user_id")) if payload.get("user_id") else None
        profile = profile_map.get(ledger_user_id or "")
        ledger_task_id = str(payload.get("task_id")) if payload.get("task_id") else None
        ledger_connector_id = str(payload.get("connector_id")) if payload.get("connector_id") else None
        connector_display_name = (
            str(payload.get("connector_display_name"))
            if payload.get("connector_display_name")
            else connector_map.get(ledger_connector_id or "")
        )
        return TokenLedgerRecord(
            id=str(payload.get("id")),
            team_id=str(payload.get("team_id")),
            user_id=ledger_user_id,
            user_display_name=profile.display_name if profile else None,
            user_email=profile.email if profile else None,
            task_id=ledger_task_id,
            task_name=task_map.get(ledger_task_id or ""),
            connector_id=ledger_connector_id,
            connector_display_name=connector_display_name,
            phase=str(payload.get("phase")),
            stage_key=str(payload.get("stage_key")) if payload.get("stage_key") else None,
            source_key=str(payload.get("source_key")),
            model_name=str(payload.get("model_name")) if payload.get("model_name") else None,
            input_tokens=coerce_non_negative_int(payload.get("input_tokens")),
            output_tokens=coerce_non_negative_int(payload.get("output_tokens")),
            total_tokens=coerce_non_negative_int(payload.get("total_tokens")),
            calculation_method=str(payload.get("calculation_method")) if payload.get("calculation_method") else None,
            raw_usage=payload.get("raw_usage") if isinstance(payload.get("raw_usage"), dict) else None,
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )

    def _list_task_names(self, team_id: str, task_ids: list[str], *, access_token: str) -> dict[str, str]:
        normalized_ids = sorted({item for item in task_ids if item})
        if not normalized_ids:
            return {}
        quoted_in_list = _quoted_in_list(normalized_ids)
        payload = self._request_json(
            path=(
                "ai_tasks"
                f"?select=id,name&team_id=eq.{quote(team_id, safe='')}"
                f"&id=in.({quoted_in_list})"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task-name response from Supabase.")
        return {
            str(item.get("id")): str(item.get("name") or item.get("id"))
            for item in payload
            if isinstance(item, dict) and item.get("id")
        }

    def _list_connector_names(self, team_id: str, connector_ids: list[str], *, access_token: str) -> dict[str, str]:
        normalized_ids = sorted({item for item in connector_ids if item})
        if not normalized_ids:
            return {}
        quoted_in_list = _quoted_in_list(normalized_ids)
        payload = self._request_json(
            path=(
                "ai_connectors"
                f"?select=id,display_name&team_id=eq.{quote(team_id, safe='')}"
                f"&id=in.({quoted_in_list})"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected connector-name response from Supabase.")
        return {
            str(item.get("id")): str(item.get("display_name") or item.get("id"))
            for item in payload
            if isinstance(item, dict) and item.get("id")
        }


def _quoted_in_list(values: list[str]) -> str:
    in_list = ",".join(f'"{item}"' for item in values)
    return quote(in_list, safe='(),"')


def _unwrap_single_record(payload: Any, action: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return payload[0]
    raise ConnectionError(f"Unexpected Supabase response shape during {action}.")
