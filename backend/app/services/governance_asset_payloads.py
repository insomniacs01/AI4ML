from __future__ import annotations

from typing import Any

from backend.app.models.governance import (
    PlatformAssetCreateRequest,
    PlatformAssetForkRequest,
    PlatformAssetPublishRequest,
    PlatformAssetRecord,
    PlatformAssetReviewRequest,
    TeamProfileRecord,
)


SUPPORTED_PLATFORM_ASSET_TYPES = {"prompt", "plan"}


def create_asset_body(team_id: str, created_by: str, payload: PlatformAssetCreateRequest) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "created_by": created_by,
        "asset_type": payload.asset_type,
        "title": payload.title,
        "description": payload.description,
        "storage_path": payload.storage_path,
        "category": payload.category,
        "tags": normalize_asset_tags(payload.tags),
        "visibility": payload.visibility,
        "version": payload.version,
        "source_task_id": payload.source_task_id,
        "model_card": payload.model_card,
        "metadata": payload.metadata,
        "review_status": payload.review_status,
    }


def review_asset_body(payload: PlatformAssetReviewRequest) -> dict[str, Any]:
    body: dict[str, Any] = {"review_status": payload.review_status}
    if payload.category is not None:
        body["category"] = payload.category
    if payload.tags is not None:
        body["tags"] = normalize_asset_tags(payload.tags)
    if payload.visibility is not None:
        body["visibility"] = payload.visibility
    return body


def publish_asset_body(
    existing: PlatformAssetRecord,
    actor_id: str,
    payload: PlatformAssetPublishRequest,
    *,
    published_at: str,
) -> dict[str, Any]:
    metadata = dict(existing.metadata or {})
    metadata.update(payload.metadata or {})
    metadata["marketplace"] = {
        **(metadata.get("marketplace") if isinstance(metadata.get("marketplace"), dict) else {}),
        "published": True,
        "published_at": published_at,
        "published_by": actor_id,
        "note": payload.note,
    }
    return {
        "review_status": "published",
        "visibility": payload.visibility,
        "published_at": published_at,
        "metadata": metadata,
    }


def fork_asset_body(
    team_id: str,
    created_by: str,
    source: PlatformAssetRecord,
    payload: PlatformAssetForkRequest,
    *,
    forked_at: str,
) -> dict[str, Any]:
    source_metadata = source.metadata if isinstance(source.metadata, dict) else {}
    fork_metadata = {
        **(payload.metadata or {}),
        "fork": {
            "forked_from_asset_id": source.id,
            "forked_from_team_id": source.team_id,
            "forked_from_title": source.title,
            "forked_from_type": source.asset_type,
            "forked_by": created_by,
            "forked_at": forked_at,
            "source_storage_path": source.storage_path,
            "source_review_status": source.review_status,
        },
        "source_metadata": source_metadata,
    }
    return {
        "team_id": team_id,
        "created_by": created_by,
        "asset_type": source.asset_type,
        "title": payload.title or f"Fork of {source.title}",
        "description": payload.description if payload.description is not None else source.description,
        "storage_path": source.storage_path,
        "category": source.category,
        "tags": normalize_asset_tags(source.tags),
        "visibility": "private",
        "version": payload.version or source.version,
        "source_task_id": source.source_task_id,
        "source_asset_id": source.id,
        "model_card": source.model_card,
        "metadata": fork_metadata,
        "review_status": payload.review_status,
    }


def asset_from_payload(
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
        tags=normalize_asset_tags(payload.get("tags")),
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


def unwrap_single_record(payload: Any, action: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return payload[0]
    raise ConnectionError(f"Unexpected Supabase response shape during {action}.")


def normalize_asset_tags(value: Any) -> list[str]:
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
