from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from threading import Lock
import time
from typing import Any

from backend.app.models.governance import (
    TeamMemberRecord,
    TeamProfileRecord,
    TeamSettingsRecord,
    TeamSettingsUpdateRequest,
)
from backend.app.services.governance_http import unwrap_single_record
from backend.app.services.governance_team_ownership import resolve_ownership_transfer
from backend.app.services.governance_team_records import (
    team_member_from_payload,
    team_settings_from_payload,
)
from backend.app.services.governance_team_profiles import list_team_profiles, update_team_profile
from backend.app.services.governance_team_member_updates import (
    update_team_member_role,
    update_team_member_status,
)
from backend.app.services.governance_team_queries import (
    team_members_path,
    team_path,
    team_update_path,
)

RequestJson = Callable[..., Any]
TEAM_MEMBER_CACHE_TTL_SECONDS = 30.0
TEAM_SETTINGS_CACHE_TTL_SECONDS = 30.0


class GovernanceTeamRepository:
    _team_settings_from_payload = staticmethod(team_settings_from_payload)
    _member_record_from_payload = staticmethod(team_member_from_payload)
    _resolve_ownership_transfer = staticmethod(resolve_ownership_transfer)
    _unwrap_single_record = staticmethod(unwrap_single_record)

    def __init__(self, *, request_json: RequestJson) -> None:
        self._request_json = request_json
        self._member_cache: dict[tuple[str, str], tuple[float, list[TeamMemberRecord]]] = {}
        self._member_cache_lock = Lock()
        self._settings_cache: dict[tuple[str, str], tuple[float, TeamSettingsRecord]] = {}
        self._settings_cache_lock = Lock()

    def list_members(self, team_id: str, *, access_token: str) -> list[TeamMemberRecord]:
        cache_key = self._member_cache_key(team_id, access_token=access_token)
        cached = self._cached_members(cache_key)
        if cached is not None:
            return cached

        member_payload = self._request_json(
            path=team_members_path(team_id),
            access_token=access_token,
        )
        if not isinstance(member_payload, list):
            raise ConnectionError("Unexpected team-members response from Supabase.")

        profiles = self.list_profiles(
            [str(item.get("user_id")) for item in member_payload if isinstance(item, dict)],
            access_token=access_token,
        )
        profile_map = {item.user_id: item for item in profiles}
        records = [
            self._member_record_from_payload(
                item,
                profile=profile_map.get(str(item.get("user_id"))),
            )
            for item in member_payload
            if isinstance(item, dict)
        ]
        self._store_member_cache(cache_key, records)
        return list(records)

    def get_team(self, team_id: str, *, access_token: str) -> dict[str, Any] | None:
        payload = self._request_json(
            path=team_path(team_id),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected team response from Supabase.")
        return payload[0] if payload else None

    def get_team_settings(self, team_id: str, *, access_token: str) -> TeamSettingsRecord | None:
        cache_key = self._team_cache_key(team_id, access_token=access_token)
        cached = self._cached_settings(cache_key)
        if cached is not None:
            return cached

        team = self.get_team(team_id, access_token=access_token)
        if team is None:
            return None
        members = self.list_members(team_id, access_token=access_token)
        settings = self._team_settings_from_payload(team, members)
        self._store_settings_cache(cache_key, settings)
        return settings

    def update_team_settings(
        self,
        team_id: str,
        payload: TeamSettingsUpdateRequest,
        *,
        access_token: str,
    ) -> TeamSettingsRecord:
        body: dict[str, Any] = {}
        if payload.name is not None:
            body["name"] = payload.name.strip()
        if payload.description is not None:
            body["description"] = payload.description.strip() or None
        if payload.status is not None:
            body["status"] = payload.status
        if not body:
            current = self.get_team_settings(team_id, access_token=access_token)
            if current is None:
                raise ValueError("team not found")
            return current

        updated_payload = self._request_json(
            path=team_update_path(team_id),
            access_token=access_token,
            method="PATCH",
            body=body,
        )
        updated = self._unwrap_single_record(updated_payload, "team settings update")
        members = self.list_members(team_id, access_token=access_token)
        settings = self._team_settings_from_payload(updated, members)
        self._store_settings_cache(self._team_cache_key(team_id, access_token=access_token), settings)
        return settings

    def transfer_ownership(
        self,
        team_id: str,
        *,
        current_owner_id: str,
        new_owner_user_id: str,
        access_token: str,
    ) -> tuple[TeamSettingsRecord, TeamMemberRecord, TeamMemberRecord]:
        members = self.list_members(team_id, access_token=access_token)
        plan = self._resolve_ownership_transfer(
            members,
            current_owner_id=current_owner_id,
            new_owner_user_id=new_owner_user_id,
        )

        if plan.is_noop:
            settings = self.get_team_settings(team_id, access_token=access_token)
            if settings is None:
                raise ValueError("team not found")
            return settings, plan.previous_owner, plan.next_owner

        promoted = self.update_member_role(
            team_id,
            plan.next_owner.user_id,
            "team_owner",
            access_token=access_token,
        )
        demoted = self.update_member_role(
            team_id,
            plan.previous_owner.user_id,
            "admin",
            access_token=access_token,
        )
        self._invalidate_settings_cache(team_id)
        settings = self.get_team_settings(team_id, access_token=access_token)
        if settings is None:
            raise ValueError("team not found")
        return settings, demoted, promoted

    def update_member_role(self, team_id: str, user_id: str, role: str, *, access_token: str) -> TeamMemberRecord:
        member = update_team_member_role(
            self._request_json,
            self.list_profiles,
            team_id,
            user_id,
            role,
            access_token=access_token,
        )
        self._invalidate_member_cache(team_id)
        self._invalidate_settings_cache(team_id)
        return member

    def update_member_status(
        self,
        team_id: str,
        user_id: str,
        member_status: str,
        *,
        access_token: str,
    ) -> TeamMemberRecord:
        member = update_team_member_status(
            self._request_json,
            self.list_profiles,
            team_id,
            user_id,
            member_status,
            access_token=access_token,
        )
        self._invalidate_member_cache(team_id)
        self._invalidate_settings_cache(team_id)
        return member

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None,
        access_token: str,
    ) -> TeamProfileRecord:
        profile = update_team_profile(
            self._request_json,
            user_id,
            display_name=display_name,
            access_token=access_token,
        )
        self._invalidate_member_cache()
        self._invalidate_settings_cache()
        return profile

    def list_profiles(self, user_ids: list[str], *, access_token: str) -> list[TeamProfileRecord]:
        return list_team_profiles(
            self._request_json,
            user_ids,
            access_token=access_token,
        )

    def _cached_members(self, cache_key: tuple[str, str]) -> list[TeamMemberRecord] | None:
        with self._member_cache_lock:
            cached = self._member_cache.get(cache_key)
            if not cached:
                return None
            cached_at, records = cached
            if time.monotonic() - cached_at >= TEAM_MEMBER_CACHE_TTL_SECONDS:
                self._member_cache.pop(cache_key, None)
                return None
            return list(records)

    def _store_member_cache(self, cache_key: tuple[str, str], records: list[TeamMemberRecord]) -> None:
        with self._member_cache_lock:
            self._member_cache[cache_key] = (time.monotonic(), list(records))

    def _invalidate_member_cache(self, team_id: str | None = None) -> None:
        with self._member_cache_lock:
            if team_id is None:
                self._member_cache.clear()
                return
            stale_keys = [key for key in self._member_cache if key[1] == team_id]
            for key in stale_keys:
                self._member_cache.pop(key, None)

    @staticmethod
    def _member_cache_key(team_id: str, *, access_token: str) -> tuple[str, str]:
        return GovernanceTeamRepository._team_cache_key(team_id, access_token=access_token)

    def _cached_settings(self, cache_key: tuple[str, str]) -> TeamSettingsRecord | None:
        with self._settings_cache_lock:
            cached = self._settings_cache.get(cache_key)
            if not cached:
                return None
            cached_at, record = cached
            if time.monotonic() - cached_at >= TEAM_SETTINGS_CACHE_TTL_SECONDS:
                self._settings_cache.pop(cache_key, None)
                return None
            return record.model_copy(deep=True)

    def _store_settings_cache(self, cache_key: tuple[str, str], record: TeamSettingsRecord) -> None:
        with self._settings_cache_lock:
            self._settings_cache[cache_key] = (time.monotonic(), record.model_copy(deep=True))

    def _invalidate_settings_cache(self, team_id: str | None = None) -> None:
        with self._settings_cache_lock:
            if team_id is None:
                self._settings_cache.clear()
                return
            stale_keys = [key for key in self._settings_cache if key[1] == team_id]
            for key in stale_keys:
                self._settings_cache.pop(key, None)

    @staticmethod
    def _team_cache_key(team_id: str, *, access_token: str) -> tuple[str, str]:
        token_key = sha256(access_token.encode("utf-8")).hexdigest()
        return token_key, team_id
