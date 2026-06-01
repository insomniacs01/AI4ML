from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.services.task_local_storage import TaskLocalStorage
from backend.app.services.task_uploads import validate_upload_filename


def test_validate_upload_filename_accepts_excel_files() -> None:
    assert validate_upload_filename("ENB2012_data.xlsx") == "ENB2012_data.xlsx"


def test_validate_upload_filename_rejects_path_separators() -> None:
    with pytest.raises(HTTPException):
        validate_upload_filename("../ENB2012_data.xlsx")


def test_dataset_upload_path_uses_task_dataset_directory(tmp_path: Path) -> None:
    storage = TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs")

    upload_path = storage.dataset_upload_path("team-1", "task-1", "ENB2012_data.xlsx")

    assert upload_path == tmp_path / "tasks" / "task-1" / "dataset" / "ENB2012_data.xlsx"


def test_clear_dataset_upload_dir_removes_stale_files(tmp_path: Path) -> None:
    storage = TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs")
    stale_path = storage.dataset_upload_path("team-1", "task-1", "old.csv")
    stale_path.write_text("a,b\n1,2\n", encoding="utf-8")

    upload_dir = storage.clear_dataset_upload_dir("team-1", "task-1")

    assert upload_dir == tmp_path / "tasks" / "task-1" / "dataset"
    assert upload_dir.is_dir()
    assert list(upload_dir.iterdir()) == []
