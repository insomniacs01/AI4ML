from __future__ import annotations

from backend.app.models.task import WorkflowStage
from backend.app.services.task_stage_repository_paths import (
    stage_record_lookup_path,
    stage_record_update_path,
    stage_records_path,
)


def test_stage_records_path_quotes_identifiers() -> None:
    assert stage_records_path("team/1", "task 1") == (
        "workflow_stage_records?select=*&team_id=eq.team%2F1"
        "&task_id=eq.task%201&order=updated_at.desc"
    )


def test_stage_record_lookup_path_quotes_stage_and_normalizes_legacy_stage() -> None:
    assert stage_record_lookup_path("team/1", "task 1", WorkflowStage.training_validation) == (
        "workflow_stage_records?select=*&team_id=eq.team%2F1"
        "&task_id=eq.task%201&order=updated_at.desc"
        "&stage=eq.training_validation&limit=1"
    )


def test_stage_record_update_path_quotes_record_id() -> None:
    assert stage_record_update_path("stage/1") == "workflow_stage_records?id=eq.stage%2F1"
