from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.governance import (
    PlatformAssetCreateRequest,
    PlatformAssetForkRequest,
    PlatformAssetPublishRequest,
    PlatformAssetRecord,
    PlatformAssetReviewRequest,
    TeamProfileRecord,
)
from backend.app.services.governance_asset_payloads import (
    asset_from_payload,
    create_asset_body,
    fork_asset_body,
    normalize_asset_tags,
    publish_asset_body,
    review_asset_body,
    unwrap_single_record,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_normalize_asset_tags_dedupes_trims_truncates_and_limits() -> None:
    tags = normalize_asset_tags([" alpha ", "alpha", "", "b" * 100, *[f"tag-{index}" for index in range(30)]])

    assert tags[0] == "alpha"
    assert tags[1] == "b" * 80
    assert len(tags) == 20


def test_create_and_review_asset_bodies_normalize_tags() -> None:
    create_body = create_asset_body(
        "team-1",
        "user-1",
        PlatformAssetCreateRequest(asset_type="prompt", title="Prompt", tags=[" alpha ", "alpha", "beta"]),
    )
    review_body = review_asset_body(
        PlatformAssetReviewRequest(review_status="approved", tags=[" beta ", "beta"], visibility="team")
    )

    assert create_body["team_id"] == "team-1"
    assert create_body["created_by"] == "user-1"
    assert create_body["tags"] == ["alpha", "beta"]
    assert review_body == {"review_status": "approved", "tags": ["beta"], "visibility": "team"}


def test_publish_asset_body_merges_metadata_with_single_published_timestamp() -> None:
    existing = _asset_record(metadata={"keep": True, "marketplace": {"previous": "value"}})

    body = publish_asset_body(
        existing,
        "publisher-1",
        PlatformAssetPublishRequest(note="Ship it.", metadata={"extra": 1}),
        published_at="2026-01-01T00:00:00+00:00",
    )

    assert body["review_status"] == "published"
    assert body["published_at"] == "2026-01-01T00:00:00+00:00"
    assert body["metadata"]["keep"] is True
    assert body["metadata"]["extra"] == 1
    assert body["metadata"]["marketplace"] == {
        "previous": "value",
        "published": True,
        "published_at": "2026-01-01T00:00:00+00:00",
        "published_by": "publisher-1",
        "note": "Ship it.",
    }


def test_fork_asset_body_preserves_source_identity_and_payload_overrides() -> None:
    source = _asset_record(
        id="asset-source",
        title="Source asset",
        tags=["alpha", "beta"],
        metadata={"source": True},
    )

    body = fork_asset_body(
        "team-2",
        "user-2",
        source,
        PlatformAssetForkRequest(title="Forked", version="2.0.0", metadata={"custom": True}),
        forked_at="2026-01-01T00:00:00+00:00",
    )

    assert body["team_id"] == "team-2"
    assert body["title"] == "Forked"
    assert body["version"] == "2.0.0"
    assert body["source_asset_id"] == "asset-source"
    assert body["metadata"]["custom"] is True
    assert body["metadata"]["source_metadata"] == {"source": True}
    assert body["metadata"]["fork"]["forked_from_title"] == "Source asset"


def test_asset_from_payload_attaches_creator_profile_and_sanitizes_fields() -> None:
    payload = {
        "id": "asset-1",
        "team_id": "team-1",
        "created_by": "user-1",
        "asset_type": "prompt",
        "title": "Prompt",
        "tags": "alpha, beta, alpha",
        "visibility": "",
        "metadata": {"x": 1},
        "review_status": "private",
        "created_at": NOW,
        "updated_at": NOW,
    }
    profile = TeamProfileRecord(user_id="user-1", display_name="Ada", email="ada@example.com")

    record = asset_from_payload(payload, profile_map={"user-1": profile})

    assert record.tags == ["alpha", "beta"]
    assert record.visibility == "private"
    assert record.creator_display_name == "Ada"
    assert record.creator_email == "ada@example.com"


def test_unwrap_single_record_rejects_unexpected_shapes() -> None:
    assert unwrap_single_record([{"id": "asset-1"}], "asset create") == {"id": "asset-1"}
    with pytest.raises(ConnectionError, match="asset create"):
        unwrap_single_record([], "asset create")


def _asset_record(**overrides) -> PlatformAssetRecord:
    values = {
        "id": "asset-1",
        "team_id": "team-1",
        "created_by": "user-1",
        "asset_type": "prompt",
        "title": "Prompt",
        "description": "Description",
        "storage_path": "storage/path",
        "category": "templates",
        "tags": ["alpha"],
        "visibility": "private",
        "version": "1.0.0",
        "source_task_id": "task-1",
        "source_asset_id": None,
        "model_card": {"model": "card"},
        "metadata": {},
        "review_status": "private",
        "published_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return PlatformAssetRecord(**values)
