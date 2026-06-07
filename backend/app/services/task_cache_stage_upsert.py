from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.app.services.task_cache_upsert import existing_is_newer_or_equal


@dataclass(frozen=True)
class CachedStageState:
    updated_at: datetime | None


@dataclass(frozen=True)
class StageUpsertPlan:
    stage: str
    should_write: bool


def build_stage_upsert_plan(
    existing: CachedStageState | None,
    raw_stage: Any,
    incoming_updated_at: datetime,
) -> StageUpsertPlan:
    stage = stage_key(raw_stage)
    if existing is not None and existing_is_newer_or_equal(existing.updated_at, incoming_updated_at):
        return StageUpsertPlan(stage=stage, should_write=False)
    return StageUpsertPlan(stage=stage, should_write=True)


def stage_key(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)
