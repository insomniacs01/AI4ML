from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, UploadFile

from backend.app.api.router import register_api_routes
from backend.app.api.routes import task_dataset, task_lifecycle
from backend.app.core.config import Settings
from backend.app.models.task import DatasetProfile, TaskRecord, TaskStatus
from backend.app.services.task_local_storage import TaskLocalStorage


class _FakeTaskStore:
    def __init__(self, task: TaskRecord, storage: TaskLocalStorage) -> None:
        self.task = task
        self.storage = storage
        self.list_kwargs: dict[str, object] = {}
        self.get_kwargs: dict[str, object] = {}

    def list_tasks(self, team_id: str, **kwargs: object) -> list[TaskRecord]:
        self.list_kwargs = kwargs
        return [self.task] if team_id == self.task.team_id else []

    def get_task(self, team_id: str, task_id: str, *, access_token: str, **kwargs: object) -> TaskRecord | None:
        self.get_kwargs = kwargs
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


def test_task_list_route_omits_none_summary_fields() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", "") == "/api/teams/{team_id}/tasks"
        and "GET" in getattr(route, "methods", set())
    )

    assert route.response_model_exclude_none is True


def test_list_tasks_returns_summary_payload_without_detail_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    task.dataset_profile = DatasetProfile(
        filename="large.csv",
        path="D:/large.csv",
        row_count=1000,
        column_count=40,
        columns=[],
        preview_rows=[{"large": "payload"}],
        generated_at=task.updated_at,
    )
    task.name = "任务" * 100
    task.description = "需求" * 300
    task.notes = "运行备注" * 200
    task.structured_requirements = {"large": {"payload": True}}
    store = _FakeTaskStore(task, TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs"))
    monkeypatch.setattr(task_lifecycle, "get_task_store", lambda: store)

    response = task_lifecycle.list_tasks(
        team_access=SimpleNamespace(team_id=task.team_id, access_token="token"),
    )
    payload = response.model_dump(mode="json")["items"][0]

    assert payload["id"] == task.id
    assert len(payload["name"]) == 120
    assert payload["dataset_filename"] == task.dataset_filename
    assert "description" not in payload
    assert "notes" not in payload
    assert "dataset_profile" not in payload
    assert "structured_requirements" not in payload
    assert "stage_routing" not in payload
    assert "interaction_policies" not in payload
    assert "codex_workspace_path" not in payload
    assert "codex_session_id" not in payload
    assert store.list_kwargs["allow_stale_cache"] is True


def test_list_tasks_can_return_compact_payload_for_task_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    task.dataset_filename = "compact.csv"
    task.dataset_path = "D:/large/compact.csv"
    task.codex_status = "running"
    task.name = "任务" * 100
    store = _FakeTaskStore(task, TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs"))
    monkeypatch.setattr(task_lifecycle, "get_task_store", lambda: store)

    response = task_lifecycle.list_tasks(
        compact=True,
        team_access=SimpleNamespace(team_id=task.team_id, access_token="token"),
    )
    payload = response.model_dump(mode="json")["items"][0]

    assert payload["id"] == task.id
    assert payload["created_by"] == task.created_by
    assert payload["name"] == "任务" * 60
    assert payload["status"] == task.status.value
    assert payload["dataset_filename"] == "compact.csv"
    assert "created_at" in payload
    assert "updated_at" in payload
    assert "team_id" not in payload
    assert "creator_user_id" not in payload
    assert "dataset_path" not in payload
    assert "codex_status" not in payload
    assert "description" not in payload
    assert store.list_kwargs["allow_stale_cache"] is True


def test_runtime_task_list_uses_status_filter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    task.status = TaskStatus.running
    store = _FakeTaskStore(task, TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs"))
    monkeypatch.setattr(task_lifecycle, "get_task_store", lambda: store)

    response = task_lifecycle.list_tasks(
        runtime_only=True,
        team_access=SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert response.items[0].id == task.id
    assert store.list_kwargs["limit"] == 20
    assert store.list_kwargs["statuses"] == task_lifecycle.RUNTIME_TASK_STATUSES


def test_get_task_can_skip_codex_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = _task()
    store = _FakeTaskStore(task, TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs"))

    def fail_if_synced(*args: object, **kwargs: object) -> None:
        raise AssertionError("sync=false task detail route must not sync Codex state")

    monkeypatch.setattr(task_lifecycle, "get_task_store", lambda: store)
    monkeypatch.setattr(task_lifecycle, "sync_codex_task_state", fail_if_synced)

    result = task_lifecycle.get_task(
        task.id,
        sync=False,
        team_access=SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert result is task
    assert result.executor_type == "codex"
    assert store.get_kwargs["prefer_cache"] is True
    assert store.get_kwargs["allow_stale_cache"] is True


def test_get_task_sync_reads_authoritative_task_before_codex_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _task()
    store = _FakeTaskStore(task, TaskLocalStorage(dataset_root_dir=tmp_path / "tasks", run_output_dir=tmp_path / "runs"))

    def sync_task(task_arg: TaskRecord, settings: object, **kwargs: object) -> tuple[TaskRecord, dict[str, object]]:
        assert task_arg is task
        assert kwargs["task_store"] is store
        return task_arg, {}

    monkeypatch.setattr(task_lifecycle, "get_task_store", lambda: store)
    monkeypatch.setattr(task_lifecycle, "get_settings", lambda: object())
    monkeypatch.setattr(task_lifecycle, "sync_codex_task_state", sync_task)

    result = task_lifecycle.get_task(
        task.id,
        sync=True,
        team_access=SimpleNamespace(team_id=task.team_id, access_token="token"),
    )

    assert result is task
    assert store.get_kwargs["prefer_cache"] is False
    assert store.get_kwargs["allow_stale_cache"] is False
