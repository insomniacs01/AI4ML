from __future__ import annotations

from typing import get_args

from fastapi import FastAPI
import pytest
from pydantic import ValidationError

from backend.app.api.router import register_api_routes
from backend.app.api.routes.team_assets import asset_type_allows_results
from backend.app.core.config import Settings
from backend.app.models.governance import AssetType, PlatformAssetCreateRequest


def test_platform_assets_are_prompt_and_plan_only() -> None:
    assert set(get_args(AssetType)) == {"prompt", "plan"}
    assert PlatformAssetCreateRequest(asset_type="prompt", title="Prompt").asset_type == "prompt"
    assert PlatformAssetCreateRequest(asset_type="plan", title="Plan").asset_type == "plan"

    with pytest.raises(ValidationError):
        PlatformAssetCreateRequest(asset_type="dataset", title="Dataset")


def test_team_asset_type_filter_allows_only_supported_asset_types() -> None:
    assert asset_type_allows_results(None)
    assert asset_type_allows_results("prompt")
    assert asset_type_allows_results("plan")
    assert not asset_type_allows_results("dataset")


def test_team_asset_routes_remain_registered_under_team_prefix() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route_paths = {route.path for route in app.routes}

    assert "/api/teams/{team_id}/assets" in route_paths
    assert "/api/teams/{team_id}/assets/{asset_id}/review" in route_paths
    assert "/api/teams/{team_id}/assets/{asset_id}/publish" in route_paths
    assert "/api/teams/{team_id}/assets/{asset_id}/fork" in route_paths
