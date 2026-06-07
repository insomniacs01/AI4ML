from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.models.task import WorkflowStage
from backend.app.services.task_cache_stage_upsert import CachedStageState, build_stage_upsert_plan, stage_key


def test_stage_key_uses_enum_value_and_preserves_plain_strings() -> None:
    assert stage_key(WorkflowStage.training_validation) == "training_validation"
    assert stage_key("custom-stage") == "custom-stage"


def test_stage_upsert_plan_writes_when_stage_is_not_cached() -> None:
    now = datetime.now(timezone.utc)

    plan = build_stage_upsert_plan(None, WorkflowStage.training_validation, now)

    assert plan.stage == "training_validation"
    assert plan.should_write is True


def test_stage_upsert_plan_skips_existing_newer_or_equal_stage() -> None:
    now = datetime.now(timezone.utc)
    existing = CachedStageState(updated_at=now)

    assert build_stage_upsert_plan(existing, WorkflowStage.training_validation, now).should_write is False
    assert build_stage_upsert_plan(existing, WorkflowStage.training_validation, now - timedelta(minutes=1)).should_write is False


def test_stage_upsert_plan_writes_newer_incoming_stage() -> None:
    now = datetime.now(timezone.utc)
    existing = CachedStageState(updated_at=now)

    plan = build_stage_upsert_plan(existing, WorkflowStage.training_validation, now + timedelta(minutes=1))

    assert plan.should_write is True
