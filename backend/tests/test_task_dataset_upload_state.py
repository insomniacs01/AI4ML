from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import DatasetProfile, RunAttempt, TaskRecord, TaskStatus
from backend.app.services.task_dataset_upload_state import apply_uploaded_dataset_to_task


def _task(**overrides: object) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = {
        "id": "task-upload-state",
        "team_id": "team-1",
        "created_by": "user-1",
        "name": "Upload State",
        "description": "Upload state task.",
        "status": TaskStatus.completed,
        "label_column": "Y1,Y2",
        "codex_workspace_path": "old-workspace",
        "codex_session_id": "old-session",
        "codex_thread_id": "old-thread",
        "codex_status": "completed",
        "codex_started_at": now,
        "codex_finished_at": now,
        "last_run_attempt": RunAttempt(output_dir="old-attempt"),
        "structured_requirements": {"dataset_profile": {"old": True}},
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return TaskRecord(**payload)


def test_apply_uploaded_dataset_to_task_resets_codex_state_and_sets_dataset_input(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    uploaded_file_path = dataset_dir / "train.xlsx"
    task = _task()

    updated = apply_uploaded_dataset_to_task(
        task,
        filename="train.xlsx",
        dataset_dir=dataset_dir,
        uploaded_file_path=uploaded_file_path,
        size_bytes=128,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        dataset_profile=None,
        profile_error="uploaded file is not a CSV",
    )

    assert updated.status == TaskStatus.uploaded
    assert updated.dataset_filename == "train.xlsx"
    assert updated.dataset_path == str(dataset_dir)
    assert updated.dataset_profile is None
    assert updated.codex_workspace_path is None
    assert updated.codex_session_id is None
    assert updated.codex_thread_id is None
    assert updated.codex_status is None
    assert updated.codex_started_at is None
    assert updated.codex_finished_at is None
    assert updated.last_run is None
    assert updated.last_run_attempt is None

    requirements = updated.structured_requirements or {}
    assert requirements["dataset_input"]["path"] == str(dataset_dir)
    assert requirements["dataset_input"]["path_type"] == "directory"
    assert requirements["dataset_files"] == [
        {
            "filename": "train.xlsx",
            "path": str(uploaded_file_path),
            "size_bytes": 128,
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    ]
    assert requirements["dataset_profile_error"] == "uploaded file is not a CSV"
    assert "dataset_profile" not in requirements
    assert requirements["target_hint"] == "Y1,Y2"
    assert requirements["target_columns_hint"] == ["Y1", "Y2"]
    assert requirements["target_definition"] == {
        "target_mode": "multi_target",
        "target_columns": ["Y1", "Y2"],
        "source": "user_input",
    }


def test_apply_uploaded_dataset_to_task_stores_profile_and_clears_profile_error(tmp_path: Path) -> None:
    generated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    profile = DatasetProfile(
        filename="train.csv",
        path=str(tmp_path / "dataset" / "train.csv"),
        row_count=2,
        column_count=2,
        columns=[],
        preview_rows=[{"x": "1", "y": "2"}],
        target_column="y",
        generated_at=generated_at,
    )
    task = _task(
        label_column="y",
        structured_requirements={
            "dataset_profile_error": "old error",
        },
    )

    updated = apply_uploaded_dataset_to_task(
        task,
        filename="train.csv",
        dataset_dir=tmp_path / "dataset",
        uploaded_file_path=tmp_path / "dataset" / "train.csv",
        size_bytes=64,
        content_type="text/csv",
        dataset_profile=profile,
        profile_error="",
    )

    requirements = updated.structured_requirements or {}
    assert requirements["dataset_profile"]["filename"] == "train.csv"
    assert requirements["dataset_profile"]["row_count"] == 2
    assert requirements["dataset_profile"]["generated_at"] == "2026-01-02T00:00:00Z"
    assert "dataset_profile_error" not in requirements
    assert requirements["target_columns_hint"] == ["y"]
