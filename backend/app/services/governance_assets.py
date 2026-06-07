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
            asset_from_payload(item, profile_map=profile_map)
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
            body=create_asset_body(team_id, created_by, payload),
        )
        record = unwrap_single_record(created, "asset create")
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
