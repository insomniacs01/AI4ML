from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
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

SUPPORTED_PLATFORM_ASSET_TYPES = {"prompt", "plan"}

RequestJson = Callable[..., Any]
ListProfiles = Callable[..., list[TeamProfileRecord]]


class PlatformAssetRepository:
    def __init__(
        self,
        *,
        request_json: RequestJson,
        list_profiles: ListProfiles,
    ) -> None:
        self._request_json = request_json
        self._list_profiles = list_profiles

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
        path = (
            "platform_assets"
            f"?select=*&team_id=eq.{quote(team_id, safe='')}"
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

        profile_map = self._profile_map_for_payload(payload, access_token=access_token)
        return [
            self._asset_from_payload(item, profile_map=profile_map)
            for item in payload
            if isinstance(item, dict) and item.get("asset_type") in SUPPORTED_PLATFORM_ASSET_TYPES
        ]

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
        return self._asset_with_creator(payload[0], access_token=access_token)

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
            body={
                "team_id": team_id,
                "created_by": created_by,
                "asset_type": payload.asset_type,
                "title": payload.title,
                "description": payload.description,
                "storage_path": payload.storage_path,
                "category": payload.category,
                "tags": _normalize_tags(payload.tags),
                "visibility": payload.visibility,
                "version": payload.version,
                "source_task_id": payload.source_task_id,
                "model_card": payload.model_card,
                "metadata": payload.metadata,
                "review_status": payload.review_status,
            },
        )
        record = self._unwrap_single_record(created, "asset create")
        return self._asset_with_creator(record, access_token=access_token)

    def review_asset(
        self,
        team_id: str,
        asset_id: str,
        payload: PlatformAssetReviewRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        body: dict[str, Any] = {"review_status": payload.review_status}
        if payload.category is not None:
            body["category"] = payload.category
        if payload.tags is not None:
            body["tags"] = _normalize_tags(payload.tags)
        if payload.visibility is not None:
            body["visibility"] = payload.visibility
        updated = self._request_json(
            path=(
                "platform_assets"
                f"?team_id=eq.{quote(team_id, safe='')}&id=eq.{quote(asset_id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body=body,
        )
        record = self._unwrap_single_record(updated, "asset review")
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
        metadata = dict(existing.metadata or {})
        metadata.update(payload.metadata or {})
        metadata["marketplace"] = {
            **(metadata.get("marketplace") if isinstance(metadata.get("marketplace"), dict) else {}),
            "published": True,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "published_by": actor_id,
            "note": payload.note,
        }
        updated = self._request_json(
            path=(
                "platform_assets"
                f"?team_id=eq.{quote(team_id, safe='')}&id=eq.{quote(asset_id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body={
                "review_status": "published",
                "visibility": payload.visibility,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata,
            },
        )
        record = self._unwrap_single_record(updated, "asset publish")
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
        source_metadata = source.metadata if isinstance(source.metadata, dict) else {}
        fork_metadata = {
            **(payload.metadata or {}),
            "fork": {
                "forked_from_asset_id": source.id,
                "forked_from_team_id": source.team_id,
                "forked_from_title": source.title,
                "forked_from_type": source.asset_type,
                "forked_by": created_by,
                "forked_at": now,
                "source_storage_path": source.storage_path,
                "source_review_status": source.review_status,
            },
            "source_metadata": source_metadata,
        }
        created = self._request_json(
            path="platform_assets",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "created_by": created_by,
                "asset_type": source.asset_type,
                "title": payload.title or f"Fork of {source.title}",
                "description": payload.description if payload.description is not None else source.description,
                "storage_path": source.storage_path,
                "category": source.category,
                "tags": _normalize_tags(source.tags),
                "visibility": "private",
                "version": payload.version or source.version,
                "source_task_id": source.source_task_id,
                "source_asset_id": source.id,
                "model_card": source.model_card,
                "metadata": fork_metadata,
                "review_status": payload.review_status,
            },
        )
        record = self._unwrap_single_record(created, "asset fork")
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
        return True

    def _asset_with_creator(self, payload: dict[str, Any], *, access_token: str) -> PlatformAssetRecord:
        return self._asset_from_payload(
            payload,
            profile_map=self._profile_map_for_payload([payload], access_token=access_token),
        )

    def _profile_map_for_payload(self, payload: list[Any], *, access_token: str) -> dict[str, TeamProfileRecord]:
        profiles = self._list_profiles(
            [str(item.get("created_by")) for item in payload if isinstance(item, dict) and item.get("created_by")],
            access_token=access_token,
        )
        return {item.user_id: item for item in profiles}

    @staticmethod
    def _asset_from_payload(
        payload: dict[str, Any],
        *,
        profile_map: dict[str, TeamProfileRecord],
    ) -> PlatformAssetRecord:
        creator_id = str(payload.get("created_by")) if payload.get("created_by") else None
        profile = profile_map.get(creator_id or "")
        return PlatformAssetRecord(
            id=str(payload.get("id")),
            team_id=str(payload.get("team_id")),
            created_by=creator_id,
            asset_type=str(payload.get("asset_type")),
            title=str(payload.get("title")),
            description=str(payload.get("description")) if payload.get("description") else None,
            storage_path=str(payload.get("storage_path")) if payload.get("storage_path") else None,
            category=str(payload.get("category")) if payload.get("category") else None,
            tags=_normalize_tags(payload.get("tags")),
            visibility=str(payload.get("visibility") or "private"),
            version=str(payload.get("version")) if payload.get("version") else None,
            source_task_id=str(payload.get("source_task_id")) if payload.get("source_task_id") else None,
            source_asset_id=str(payload.get("source_asset_id")) if payload.get("source_asset_id") else None,
            model_card=payload.get("model_card") if isinstance(payload.get("model_card"), dict) else None,
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
            review_status=str(payload.get("review_status", "private")),
            published_at=payload.get("published_at"),
            creator_display_name=profile.display_name if profile else None,
            creator_email=profile.email if profile else None,
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )

    @staticmethod
    def _unwrap_single_record(payload: Any, action: str) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        raise ConnectionError(f"Unexpected Supabase response shape during {action}.")


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items: list[Any]
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        raw_items = value
    elif isinstance(value, tuple):
        raw_items = list(value)
    else:
        return []

    tags: list[str] = []
    for item in raw_items:
        tag = str(item).strip()
        if tag and tag not in tags:
            tags.append(tag[:80])
    return tags[:20]
