from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status
from fastapi import FastAPI

from backend.app.api.router import register_api_routes
from backend.app.api.routes.task_run import run_task
from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord, TaskRunRequest, TaskStatus


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-run-route",
        team_id="team-1",
        created_by="user-1",
        name="Run route",
        description="Route error mapping.",
        status=TaskStatus.uploaded,
        dataset_path="data.csv",
        created_at=now,
        updated_at=now,
    )


def test_task_run_route_remains_registered_under_task_prefix() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route_methods = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("POST", "/api/teams/{team_id}/tasks/{task_id}/run") in route_methods


def test_run_task_maps_preflight_permission_errors_to_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task()

    class Store:
        def get_task(self, team_id: str, task_id: str, *, access_token: str) -> TaskRecord | None:
            return task

    def deny_preflight(*args: object, **kwargs: object) -> None:
        raise PermissionError("Supabase rejected task preflight.")

    monkeypatch.setattr("backend.app.api.routes.task_run.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.api.routes.task_run.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.api.routes.task_run.assert_task_run_preflight", deny_preflight)

    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    with pytest.raises(HTTPException) as raised:
        run_task(task.id, TaskRunRequest(), team_access)

    assert raised.value.status_code == status.HTTP_403_FORBIDDEN
    assert raised.value.detail == "Supabase rejected task preflight."
