from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from backend.app.models.governance import AssetType, PlatformAssetCreateRequest


def test_platform_assets_are_prompt_and_plan_only() -> None:
    assert set(get_args(AssetType)) == {"prompt", "plan"}
    assert PlatformAssetCreateRequest(asset_type="prompt", title="Prompt").asset_type == "prompt"
    assert PlatformAssetCreateRequest(asset_type="plan", title="Plan").asset_type == "plan"

    with pytest.raises(ValidationError):
        PlatformAssetCreateRequest(asset_type="dataset", title="Dataset")
