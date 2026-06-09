from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
from hashlib import sha256
from pathlib import Path
from threading import Lock
import time
from typing import Any
from urllib.parse import quote

from backend.app.models.governance import (
    PlatformAssetCreateRequest,
    PlatformAssetForkRequest,
    PlatformAssetPublishRequest,
    PlatformAssetRecord,
    PlatformAssetReviewRequest,
    TeamProfileRecord,
)
from backend.app.services.governance_asset_payloads import (
    SUPPORTED_PLATFORM_ASSET_TYPES,
    asset_from_payload,
    create_asset_body,
    fork_asset_body,
    publish_asset_body,
    review_asset_body,
    unwrap_single_record,
)

RequestJson = Callable[..., Any]
ListProfiles = Callable[..., list[TeamProfileRecord]]
ASSET_LIST_CACHE_TTL_SECONDS = 300.0
ASSET_LIST_SELECT = ",".join(
    [
        "id",
        "team_id",
        "created_by",
        "asset_type",
        "title",
        "description",
        "category",
        "tags",
        "visibility",
        "version",
        "source_task_id",
        "source_asset_id",
        "review_status",
        "published_at",
        "created_at",
        "updated_at",
    ]
)


class PlatformAssetRepository:
    def __init__(
        self,
        *,
        request_json: RequestJson,
        list_profiles: ListProfiles,
        cache_dir: Path | None = None,
    ) -> None:
        self._request_json = request_json
        self._list_profiles = list_profiles
        self._cache_dir = cache_dir
        self._list_cache: dict[tuple[str, str, str, str, str], tuple[float, list[PlatformAssetRecord]]] = {}
        self._list_cache_lock = Lock()

    def list_assets(
        self,
        team_id: str,
        *,
        access_token: str,
        asset_type: str | None = None,
        review_status: str | None = None,
        visibility: str | None = None,
        category: str | None = None,
    ) -> list[PlatformAssetRecord]:
        cache_key = self._list_cache_key(
            team_id,
            asset_type=asset_type,
            review_status=review_status,
            visibility=visibility,
            category=category,
        )
        cached = self._cached_list(cache_key)
        if cached is not None:
            return cached
        persisted = self._read_persisted_list_cache(cache_key)
        if persisted is not None:
            self._store_list_cache(cache_key, persisted, persist=False)
            return persisted

        path = (
            "platform_assets"
            f"?select={ASSET_LIST_SELECT}&team_id=eq.{quote(team_id, safe='')}"
            "&order=updated_at.desc"
        )
        if asset_type:
            path += f"&asset_type=eq.{quote(asset_type, safe='')}"
        if review_status:
            path += f"&review_status=eq.{quote(review_status, safe='')}"
        if visibility:
            path += f"&visibility=eq.{quote(visibility, safe='')}"
        if category:
            path += f"&category=eq.{quote(category, safe='')}"

        payload = self._request_json(path=path, access_token=access_token)
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected platform-assets response from Supabase.")

        records = [
            asset_from_payload(item, profile_map={})
            for item in payload
            if isinstance(item, dict) and item.get("asset_type") in SUPPORTED_PLATFORM_ASSET_TYPES
        ]
        self._store_list_cache(cache_key, records)
        return list(records)

    def get_asset(self, team_id: str, asset_id: str, *, access_token: str) -> PlatformAssetRecord | None:
        payload = self._request_json(
            path=(
                "platform_assets"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&id=eq.{quote(asset_id, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected platform-asset detail response from Supabase.")
        if not payload:
            return None
        if payload[0].get("asset_type") not in SUPPORTED_PLATFORM_ASSET_TYPES:
            return None
        return asset_from_payload(payload[0], profile_map={})

    def create_asset(
        self,
        team_id: str,
        created_by: str,
        payload: PlatformAssetCreateRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        created = self._request_json(
            path="platform_assets",
            access_token=access_token,
            method="POST",
            body=create_asset_body(team_id, created_by, payload),
        )
        record = unwrap_single_record(created, "asset create")
        self._invalidate_list_cache(team_id)
        return self._asset_with_creator(record, access_token=access_token)

    def review_asset(
        self,
        team_id: str,
        asset_id: str,
        payload: PlatformAssetReviewRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        updated = self._request_json(
            path=(
                "platform_assets"
                f"?team_id=eq.{quote(team_id, safe='')}&id=eq.{quote(asset_id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body=review_asset_body(payload),
        )
        record = unwrap_single_record(updated, "asset review")
        self._invalidate_list_cache(team_id)
        return self._asset_with_creator(record, access_token=access_token)

    def publish_asset(
        self,
        team_id: str,
        asset_id: str,
        actor_id: str,
        payload: PlatformAssetPublishRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        existing = self.get_asset(team_id, asset_id, access_token=access_token)
        if existing is None:
            raise ValueError("asset not found")
        published_at = datetime.now(timezone.utc).isoformat()
        updated = self._request_json(
            path=(
                "platform_assets"
                f"?team_id=eq.{quote(team_id, safe='')}&id=eq.{quote(asset_id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body=publish_asset_body(existing, actor_id, payload, published_at=published_at),
        )
        record = unwrap_single_record(updated, "asset publish")
        self._invalidate_list_cache(team_id)
        return self._asset_with_creator(record, access_token=access_token)

    def fork_asset(
        self,
        team_id: str,
        created_by: str,
        source_asset_id: str,
        payload: PlatformAssetForkRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        source = self.get_asset(team_id, source_asset_id, access_token=access_token)
        if source is None:
            raise ValueError("asset not found")
        now = datetime.now(timezone.utc).isoformat()
        created = self._request_json(
            path="platform_assets",
            access_token=access_token,
            method="POST",
            body=fork_asset_body(team_id, created_by, source, payload, forked_at=now),
        )
        record = unwrap_single_record(created, "asset fork")
        self._invalidate_list_cache(team_id)
        return self._asset_with_creator(record, access_token=access_token)

    def delete_asset(self, team_id: str, asset_id: str, *, access_token: str) -> bool:
        existing = self.get_asset(team_id, asset_id, access_token=access_token)
        if existing is None:
            return False
        self._request_json(
            path=(
                "platform_assets"
                f"?team_id=eq.{quote(team_id, safe='')}&id=eq.{quote(asset_id, safe='')}"
            ),
            access_token=access_token,
            method="DELETE",
            expect_json=False,
        )
        self._invalidate_list_cache(team_id)
        return True

    def _asset_with_creator(self, payload: dict[str, Any], *, access_token: str) -> PlatformAssetRecord:
        return asset_from_payload(
            payload,
            profile_map=self._profile_map_for_payload([payload], access_token=access_token),
        )

    def _profile_map_for_payload(self, payload: list[Any], *, access_token: str) -> dict[str, TeamProfileRecord]:
        profiles = self._list_profiles(
            [str(item.get("created_by")) for item in payload if isinstance(item, dict) and item.get("created_by")],
            access_token=access_token,
        )
        return {item.user_id: item for item in profiles}

    def _cached_list(
        self,
        cache_key: tuple[str, str, str, str, str],
    ) -> list[PlatformAssetRecord] | None:
        with self._list_cache_lock:
            cached = self._list_cache.get(cache_key)
            if not cached:
                return None
            cached_at, records = cached
            if time.monotonic() - cached_at >= ASSET_LIST_CACHE_TTL_SECONDS:
                self._list_cache.pop(cache_key, None)
                return None
            return list(records)

    def _store_list_cache(
        self,
        cache_key: tuple[str, str, str, str, str],
        records: list[PlatformAssetRecord],
        *,
        persist: bool = True,
    ) -> None:
        with self._list_cache_lock:
            self._list_cache[cache_key] = (time.monotonic(), list(records))
        if persist:
            self._write_persisted_list_cache(cache_key, records)

    def _invalidate_list_cache(self, team_id: str) -> None:
        with self._list_cache_lock:
            stale_keys = [key for key in self._list_cache if key[0] == team_id]
            for key in stale_keys:
                self._list_cache.pop(key, None)
        self._delete_persisted_team_cache(team_id)

    def _read_persisted_list_cache(
        self,
        cache_key: tuple[str, str, str, str, str],
    ) -> list[PlatformAssetRecord] | None:
        cache_path = self._list_cache_path(cache_key)
        if cache_path is None or not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_at = float(payload.get("cached_at_monotonic") or 0)
            cached_wall_time = float(payload.get("cached_at") or 0)
            if cached_at > 0:
                age_seconds = time.monotonic() - cached_at
            else:
                age_seconds = time.time() - cached_wall_time
            if age_seconds < 0 or age_seconds >= ASSET_LIST_CACHE_TTL_SECONDS:
                cache_path.unlink(missing_ok=True)
                return None
            items = payload.get("items")
            if not isinstance(items, list):
                return None
            return [
                asset_from_payload(item, profile_map={})
                for item in items
                if isinstance(item, dict) and item.get("asset_type") in SUPPORTED_PLATFORM_ASSET_TYPES
            ]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _write_persisted_list_cache(
        self,
        cache_key: tuple[str, str, str, str, str],
        records: list[PlatformAssetRecord],
    ) -> None:
        cache_path = self._list_cache_path(cache_key)
        if cache_path is None:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "cached_at": time.time(),
                        "items": [record.model_dump(mode="json") for record in records],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def _delete_persisted_team_cache(self, team_id: str) -> None:
        if self._cache_dir is None:
            return
        team_prefix = f"{self._safe_cache_part(team_id)}-"
        try:
            for cache_path in self._cache_dir.glob(f"{team_prefix}*.json"):
                cache_path.unlink(missing_ok=True)
        except OSError:
            return

    def _list_cache_path(
        self,
        cache_key: tuple[str, str, str, str, str],
    ) -> Path | None:
        if self._cache_dir is None:
            return None
        team_id, asset_type, review_status, visibility, category = cache_key
        filter_hash = sha256(
            "\0".join([asset_type, review_status, visibility, category]).encode("utf-8")
        ).hexdigest()[:16]
        return self._cache_dir / f"{self._safe_cache_part(team_id)}-{filter_hash}.json"

    @staticmethod
    def _safe_cache_part(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _list_cache_key(
        team_id: str,
        *,
        asset_type: str | None,
        review_status: str | None,
        visibility: str | None,
        category: str | None,
    ) -> tuple[str, str, str, str, str]:
        return (
            team_id,
            asset_type or "",
            review_status or "",
            visibility or "",
            category or "",
        )
