from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import DatasetProfile, TaskRecord
from backend.app.services.task_repository import TaskRepository
from backend.app.services.task_repository_queries import (
    TASK_LIST_SELECT,
    TASK_SUMMARY_SELECT,
    task_detail_path,
    task_list_path,
    task_mutation_path,
)


def test_task_select_helpers_preserve_task_store_compatibility() -> None:
    assert TaskRepository._task_summary_select() == TASK_SUMMARY_SELECT
    assert TaskRepository._task_list_select() == TASK_LIST_SELECT
    assert "dataset_profile" not in TASK_SUMMARY_SELECT
    assert "dataset_profile" in TASK_LIST_SELECT


def test_task_list_path_quotes_team_and_clamps_pagination() -> None:
    path = task_list_path("team/1", lightweight=True, limit=999, offset=-3)

    assert path.startswith(f"ai_tasks?select={TASK_SUMMARY_SELECT}&team_id=eq.team%2F1&order=created_at.desc")
    assert path.endswith("&limit=500&offset=0")


def test_task_list_path_can_filter_runtime_statuses() -> None:
    path = task_list_path(
        "team",
        lightweight=True,
        limit=20,
        offset=0,
        statuses=("running", "waiting_human", "paused_for_review"),
    )

    assert f"?select={TASK_SUMMARY_SELECT}" in path
    assert "&status=in.(running,waiting_human,paused_for_review)&order=created_at.desc" in path
    assert path.endswith("&limit=20")


def test_task_list_path_can_omit_limit_and_use_detail_select() -> None:
    path = task_list_path("team", lightweight=False, limit=None, offset=0)

    assert f"?select={TASK_LIST_SELECT}" in path
    assert "&limit=" not in path
    assert "&offset=" not in path


def test_task_detail_and_mutation_paths_quote_identifiers() -> None:
    assert task_detail_path("team/1", "task 1") == "ai_tasks?select=*&team_id=eq.team%2F1&id=eq.task%201&limit=1"
    assert task_mutation_path("team/1", "task 1") == "ai_tasks?team_id=eq.team%2F1&id=eq.task%201"


def test_lightweight_cached_task_projection_drops_detail_only_payloads() -> None:
    now = datetime.now(timezone.utc)
    task = TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Task 1",
        description="Train a model.",
        dataset_profile=DatasetProfile(
            filename="data.csv",
            path="D:/data.csv",
            row_count=1,
            column_count=1,
            columns=[],
            preview_rows=[{"large": "payload"}],
            generated_at=now,
        ),
        structured_requirements={"dataset_profile": {"large": "payload"}},
        interaction_policies=[],
        created_at=now,
        updated_at=now,
    )

    lightweight = TaskRepository._lightweight_records([task])[0]

    assert lightweight.id == task.id
    assert lightweight.dataset_profile is None
    assert lightweight.structured_requirements is None
    assert lightweight.last_run is None
    assert lightweight.last_run_attempt is None
