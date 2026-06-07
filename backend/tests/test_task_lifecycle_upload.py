from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, UploadFile

from backend.app.api.router import register_api_routes
from backend.app.api.routes import task_dataset
from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_local_storage import TaskLocalStorage


class _FakeTaskStore:
    def __init__(self, task: TaskRecord, storage: TaskLocalStorage) -> None:
        self.task = task
        self.storage = storage

    def get_task(self, team_id: str, task_id: str, *, access_token: str) -> TaskRecord | None:
        return self.task if team_id == self.task.team_id and task_id == self.task.id and access_token else None

    def clear_dataset_upload_dir(self, team_id: str, task_id: str) -> Path:
        return self.storage.clear_dataset_upload_dir(team_id, task_id)

    def dataset_upload_path(self, team_id: str, task_id: str, filename: str) -> Path:
        return self.storage.dataset_upload_path(team_id, task_id, filename)

    def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        self.task = task
        return task


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-xlsx-upload",
        team_id="team-1",
        created_by="user-1",
        name="Excel upload",
        description="Use X1-X8 to predict Y1 and Y2.",
        status=TaskStatus.draft,
        structured_requirements={
            "target_hint": "Y1,Y2",
            "target_columns_hint": ["Y1", "Y2"],
            "target_definition": {
                "target_mode": "multi_target",
                "target_columns": ["Y1", "Y2"],
                "source": "user_input",
            },
        },
        created_at=now,
        updated_at=now,
    )


def test_upload_dataset_accepts_excel_and_points_codex_at_dataset_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    storage = TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs")
    store = _FakeTaskStore(task, storage)
    monkeypatch.setattr(task_dataset, "get_task_store", lambda: store)
    monkeypatch.setattr(task_dataset, "_record_workflow_stage", lambda *args, **kwargs: None)
    upload = UploadFile(
        filename="ENB2012_data.xlsx",
        file=BytesIO(b"PK\x03\x04fake excel payload"),
    )
    team_access = SimpleNamespace(team_id="team-1", access_token="token", user=SimpleNamespace(id="user-1"))

    result = asyncio.run(
        task_dataset.upload_dataset(
            "task-xlsx-upload",
            auto_run=False,
            time_limit=None,
            file=upload,
            team_access=team_access,
        )
    )

    dataset_dir = tmp_path / "tasks" / "task-xlsx-upload" / "dataset"
    uploaded_file = dataset_dir / "ENB2012_data.xlsx"
    assert result.status == TaskStatus.uploaded
    assert result.dataset_filename == "ENB2012_data.xlsx"
    assert result.dataset_path == str(dataset_dir)
    assert uploaded_file.read_bytes() == b"PK\x03\x04fake excel payload"
    assert result.dataset_profile is None
    assert result.structured_requirements["dataset_input"]["path"] == str(dataset_dir)
    assert result.structured_requirements["dataset_input"]["path_type"] == "directory"
    assert result.structured_requirements["target_columns_hint"] == ["Y1", "Y2"]


def test_task_dataset_route_remains_registered_under_task_prefix() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route_methods = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("POST", "/api/teams/{team_id}/tasks/{task_id}/dataset") in route_methods
