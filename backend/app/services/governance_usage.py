from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any

from backend.app.models.governance import (
    TeamMemberRecord,
    TeamProfileRecord,
    TeamQuotaRecord,
    TokenLedgerRecord,
)
from backend.app.services.governance_quota_accounts import (
    read_existing_quota_account,
    upsert_quota_account,
)
from backend.app.services.governance_quota_listing import build_quota_records
from backend.app.services.governance_quota_records import (
    quota_record_from_payload,
    quota_scope,
)
from backend.app.services.governance_token_ledger_listing import list_token_ledger_records
from backend.app.services.governance_usage_queries import (
    connector_names_path,
    member_quota_filter,
    quota_existing_path,
    quota_accounts_path,
    scope_quota_filter,
)

RequestJson = Callable[..., Any]
ListMembers = Callable[..., list[TeamMemberRecord]]
ListProfiles = Callable[..., list[TeamProfileRecord]]
QUOTA_LIST_CACHE_TTL_SECONDS = 30.0
QUOTA_MEMBER_CACHE_TTL_SECONDS = 300.0

class GovernanceUsageRepository:
    def __init__(
        self,
        *,
        request_json: RequestJson,
        list_members: ListMembers,
        list_profiles: ListProfiles,
        member_quota_cache_dir: Path | None = None,
    ) -> None:
        self._request_json = request_json
        self._list_members = list_members
        self._list_profiles = list_profiles
        self._member_quota_cache_dir = member_quota_cache_dir
        self._quota_cache: dict[tuple[str, str], tuple[float, list[TeamQuotaRecord]]] = {}
        self._member_quota_cache: dict[tuple[str, str, str], tuple[float, TeamQuotaRecord]] = {}
        self._quota_cache_lock = Lock()

    def list_quotas(self, team_id: str, *, access_token: str) -> list[TeamQuotaRecord]:
        cache_key = self._quota_cache_key(team_id, access_token=access_token)
        cached = self._cached_quotas(cache_key)
        if cached is not None:
            return cached

        members = self._list_members(team_id, access_token=access_token)
        quota_payload = self._request_json(
            path=quota_accounts_path(team_id),
            access_token=access_token,
        )
        if not isinstance(quota_payload, list):
            raise ConnectionError("Unexpected quota response from Supabase.")

        connector_map = self._connector_map(team_id, access_token=access_token)
        records = build_quota_records(
            team_id,
            members=members,
            connector_map=connector_map,
            quota_payload=quota_payload,
        )
        self._store_quota_cache(cache_key, records)
        self._store_member_quotas_from_list(cache_key, records)
        return list(records)

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
        existing_row = read_existing_quota_account(
            self._request_json,
            team_id,
            filter_path,
            access_token=access_token,
        )
        row = upsert_quota_account(
            self._request_json,
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
        self._invalidate_quota_cache(team_id)
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
        existing_row = read_existing_quota_account(
            self._request_json,
            team_id,
            scope_filter,
            access_token=access_token,
        )
        row = upsert_quota_account(
            self._request_json,
            team_id,
            scope,
            token_quota=token_quota,
            status=status,
            warning_threshold=warning_threshold,
            existing_row=existing_row,
            update_filter=scope_filter,
            access_token=access_token,
            action="quota scope adjust",
        )
        self._invalidate_quota_cache(team_id)
        return quota_record_from_payload(team_id, row)

    def get_member_quota(
        self,
        team_id: str,
        user_id: str,
        *,
        access_token: str,
        use_cache: bool = False,
    ) -> TeamQuotaRecord:
        cache_key = self._member_quota_cache_key(team_id, user_id, access_token=access_token)
        if use_cache:
            cached = self._cached_member_quota(cache_key)
            if cached is not None:
                return cached
            persisted = self._read_persisted_member_quota(team_id, user_id)
            if persisted is not None:
                self._store_member_quota(cache_key, persisted, persist=False)
                return persisted

        payload = self._request_json(
            path=quota_existing_path(team_id, member_quota_filter(user_id)),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected member quota response from Supabase.")
        row = payload[0] if payload else {
            "team_id": team_id,
            "user_id": user_id,
            "scope_type": "member",
            "scope_key": user_id,
        }
        quota = quota_record_from_payload(team_id, row)
        if use_cache:
            self._store_member_quota(cache_key, quota)
        return quota

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

    def _cached_quotas(self, cache_key: tuple[str, str]) -> list[TeamQuotaRecord] | None:
        with self._quota_cache_lock:
            cached = self._quota_cache.get(cache_key)
            if not cached:
                return None
            cached_at, records = cached
            if time.monotonic() - cached_at >= QUOTA_LIST_CACHE_TTL_SECONDS:
                self._quota_cache.pop(cache_key, None)
                return None
            return list(records)

    def _store_quota_cache(self, cache_key: tuple[str, str], records: list[TeamQuotaRecord]) -> None:
        with self._quota_cache_lock:
            self._quota_cache[cache_key] = (time.monotonic(), list(records))

    def _cached_member_quota(self, cache_key: tuple[str, str, str]) -> TeamQuotaRecord | None:
        with self._quota_cache_lock:
            cached = self._member_quota_cache.get(cache_key)
            if cached:
                cached_at, quota = cached
                if time.monotonic() - cached_at < QUOTA_MEMBER_CACHE_TTL_SECONDS:
                    return quota
                self._member_quota_cache.pop(cache_key, None)

            list_cached = self._quota_cache.get((cache_key[0], cache_key[1]))
            if not list_cached:
                return None
            cached_at, records = list_cached
            if time.monotonic() - cached_at >= QUOTA_LIST_CACHE_TTL_SECONDS:
                self._quota_cache.pop((cache_key[0], cache_key[1]), None)
                return None
            quota = next((item for item in records if item.scope_type == "member" and item.user_id == cache_key[2]), None)
            if quota is None:
                return None
            self._member_quota_cache[cache_key] = (time.monotonic(), quota)
            return quota

    def _store_member_quota(
        self,
        cache_key: tuple[str, str, str],
        quota: TeamQuotaRecord,
        *,
        persist: bool = True,
    ) -> None:
        with self._quota_cache_lock:
            self._member_quota_cache[cache_key] = (time.monotonic(), quota)
        if persist:
            self._write_persisted_member_quota(cache_key[1], cache_key[2], quota)

    def _store_member_quotas_from_list(self, cache_key: tuple[str, str], records: list[TeamQuotaRecord]) -> None:
        cached_at = time.monotonic()
        with self._quota_cache_lock:
            for quota in records:
                if quota.scope_type == "member" and quota.user_id:
                    self._member_quota_cache[(cache_key[0], cache_key[1], quota.user_id)] = (cached_at, quota)

    def _invalidate_quota_cache(self, team_id: str) -> None:
        with self._quota_cache_lock:
            stale_keys = [key for key in self._quota_cache if key[1] == team_id]
            for key in stale_keys:
                self._quota_cache.pop(key, None)
            stale_member_keys = [key for key in self._member_quota_cache if key[1] == team_id]
            for key in stale_member_keys:
                self._member_quota_cache.pop(key, None)
        self._delete_persisted_member_quota_team_cache(team_id)

    def _read_persisted_member_quota(self, team_id: str, user_id: str) -> TeamQuotaRecord | None:
        cache_path = self._member_quota_cache_path(team_id, user_id)
        if cache_path is None or not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_at = float(payload.get("cached_at") or 0)
            age_seconds = time.time() - cached_at
            if age_seconds < 0 or age_seconds >= QUOTA_MEMBER_CACHE_TTL_SECONDS:
                cache_path.unlink(missing_ok=True)
                return None
            quota = payload.get("quota")
            if not isinstance(quota, dict):
                return None
            return TeamQuotaRecord.model_validate(quota)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _write_persisted_member_quota(self, team_id: str, user_id: str, quota: TeamQuotaRecord) -> None:
        cache_path = self._member_quota_cache_path(team_id, user_id)
        if cache_path is None:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "cached_at": time.time(),
                        "quota": quota.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def _delete_persisted_member_quota_team_cache(self, team_id: str) -> None:
        if self._member_quota_cache_dir is None:
            return
        team_prefix = f"{self._safe_cache_part(team_id)}-"
        try:
            for cache_path in self._member_quota_cache_dir.glob(f"{team_prefix}*.json"):
                cache_path.unlink(missing_ok=True)
        except OSError:
            return

    def _member_quota_cache_path(self, team_id: str, user_id: str) -> Path | None:
        if self._member_quota_cache_dir is None:
            return None
        return self._member_quota_cache_dir / (
            f"{self._safe_cache_part(team_id)}-{self._safe_cache_part(user_id)}.json"
        )

    @staticmethod
    def _safe_cache_part(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _quota_cache_key(team_id: str, *, access_token: str) -> tuple[str, str]:
        token_key = sha256(access_token.encode("utf-8")).hexdigest()
        return token_key, team_id

    @classmethod
    def _member_quota_cache_key(cls, team_id: str, user_id: str, *, access_token: str) -> tuple[str, str, str]:
        token_key, team_key = cls._quota_cache_key(team_id, access_token=access_token)
        return token_key, team_key, user_id
