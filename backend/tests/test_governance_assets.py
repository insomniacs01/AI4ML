from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.governance import PlatformAssetCreateRequest
from backend.app.services.governance_assets import ASSET_LIST_SELECT, PlatformAssetRepository


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_list_assets_does_not_fetch_creator_profiles() -> None:
    calls: list[str] = []

    def request_json(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(str(kwargs["path"]))
        return [_asset_payload()]

    def list_profiles(*args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("list_assets should not fetch creator profiles")

    repository = PlatformAssetRepository(
        request_json=request_json,
        list_profiles=list_profiles,
    )

    assets = repository.list_assets("team-1", access_token="token", visibility="team")

    assert len(assets) == 1
    assert assets[0].id == "asset-1"
    assert assets[0].creator_display_name is None
    assert calls == [
        f"platform_assets?select={ASSET_LIST_SELECT}&team_id=eq.team-1&order=updated_at.desc&visibility=eq.team"
    ]


def test_list_assets_uses_cache_until_team_asset_mutation() -> None:
    calls: list[str] = []

    def request_json(**kwargs: Any) -> Any:
        method = str(kwargs.get("method", "GET"))
        calls.append(f"{method} {kwargs['path']}")
        if method == "POST":
            return _asset_payload(id="asset-created", title=kwargs["body"]["title"])
        return [_asset_payload()]

    repository = PlatformAssetRepository(
        request_json=request_json,
        list_profiles=lambda *args, **kwargs: [],
    )

    first = repository.list_assets("team-1", access_token="token", visibility="team")
    second = repository.list_assets("team-1", access_token="token", visibility="team")

    assert first[0].id == "asset-1"
    assert second[0].id == "asset-1"
    assert calls == [
        f"GET platform_assets?select={ASSET_LIST_SELECT}&team_id=eq.team-1&order=updated_at.desc&visibility=eq.team"
    ]

    created = repository.create_asset(
        "team-1",
        "user-1",
        PlatformAssetCreateRequest(asset_type="prompt", title="Created prompt"),
        access_token="token",
    )
    refreshed = repository.list_assets("team-1", access_token="token", visibility="team")

    assert created.id == "asset-created"
    assert refreshed[0].id == "asset-1"
    assert calls == [
        f"GET platform_assets?select={ASSET_LIST_SELECT}&team_id=eq.team-1&order=updated_at.desc&visibility=eq.team",
        "POST platform_assets",
        f"GET platform_assets?select={ASSET_LIST_SELECT}&team_id=eq.team-1&order=updated_at.desc&visibility=eq.team",
    ]


def test_list_assets_cache_is_team_scoped_not_token_scoped() -> None:
    calls: list[str] = []

    def request_json(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(str(kwargs["path"]))
        return [_asset_payload()]

    repository = PlatformAssetRepository(
        request_json=request_json,
        list_profiles=lambda *args, **kwargs: [],
    )

    first = repository.list_assets("team-1", access_token="token-a", visibility="team")
    second = repository.list_assets("team-1", access_token="token-b", visibility="team")

    assert first[0].id == "asset-1"
    assert second[0].id == "asset-1"
    assert calls == [
        f"platform_assets?select={ASSET_LIST_SELECT}&team_id=eq.team-1&order=updated_at.desc&visibility=eq.team"
    ]


def test_list_assets_reads_persisted_cache_across_repository_instances(tmp_path: Path) -> None:
    calls: list[str] = []

    def request_json(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(str(kwargs["path"]))
        return [_asset_payload()]

    first_repository = PlatformAssetRepository(
        request_json=request_json,
        list_profiles=lambda *args, **kwargs: [],
        cache_dir=tmp_path,
    )
    first_repository.list_assets("team-1", access_token="token", visibility="team")

    def fail_if_remote_requested(**kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError(f"persisted cache should avoid remote asset request: {kwargs['path']}")

    second_repository = PlatformAssetRepository(
        request_json=fail_if_remote_requested,
        list_profiles=lambda *args, **kwargs: [],
        cache_dir=tmp_path,
    )

    assets = second_repository.list_assets("team-1", access_token="new-token", visibility="team")

    assert assets[0].id == "asset-1"
    assert calls == [
        f"platform_assets?select={ASSET_LIST_SELECT}&team_id=eq.team-1&order=updated_at.desc&visibility=eq.team"
    ]


def test_get_asset_does_not_fetch_creator_profiles() -> None:
    calls: list[str] = []

    def request_json(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(str(kwargs["path"]))
        return [_asset_payload()]

    def list_profiles(*args: Any, **kwargs: Any) -> list[Any]:
        raise AssertionError("get_asset should not fetch creator profiles")

    repository = PlatformAssetRepository(
        request_json=request_json,
        list_profiles=list_profiles,
    )

    asset = repository.get_asset("team-1", "asset-1", access_token="token")

    assert asset is not None
    assert asset.id == "asset-1"
    assert asset.creator_display_name is None
    assert calls == [
        "platform_assets?select=*&team_id=eq.team-1&id=eq.asset-1&limit=1"
    ]


def _asset_payload(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": "asset-1",
        "team_id": "team-1",
        "created_by": "user-1",
        "asset_type": "prompt",
        "title": "Prompt",
        "description": "Description",
        "tags": [],
        "visibility": "team",
        "metadata": {},
        "review_status": "published",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return values
