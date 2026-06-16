from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException, status
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


def test_run_task_async_start_returns_before_codex_start(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task()
    saved_tasks: list[TaskRecord] = []
    start_calls: list[TaskRecord] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, *, access_token: str) -> TaskRecord | None:
            return task

        def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
            saved_tasks.append(task)
            return task

    class HumanService:
        def assert_task_can_run(self, task: TaskRecord, *, access_token: str) -> None:
            return None

    def start_codex(task: TaskRecord, settings: object, *, token_budget: int | None = None) -> dict:
        start_calls.append(task)
        return {"sessionId": "session-1", "threadId": "thread-1", "workspacePath": "D:/runs/task"}

    monkeypatch.setattr("backend.app.api.routes.task_run.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.api.routes.task_run.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.api.routes.task_run.assert_task_run_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run._assert_codex_task_can_control_current_activity", lambda task, team_access: task)
    monkeypatch.setattr("backend.app.api.routes.task_run._assert_quota_allows_action", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run.get_task_human_collaboration_service", lambda: HumanService())
    monkeypatch.setattr("backend.app.api.routes.task_run.record_codex_running_stages", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run.start_codex_task", start_codex)

    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )
    background_tasks = BackgroundTasks()

    result = run_task(
        task.id,
        TaskRunRequest(),
        team_access,
        background_tasks=background_tasks,
        async_start=True,
    )

    assert result.status == TaskStatus.running
    assert result.codex_status == "starting"
    assert saved_tasks == [result]
    assert start_calls == []
    assert len(background_tasks.tasks) == 1


@pytest.mark.parametrize(
    ("payload", "action", "note"),
    [
        (
            TaskRunRequest(regenerate_plan=True),
            "regenerate_plan",
            "Codex 正在后台根据人工反馈重新生成建模计划。",
        ),
        (
            TaskRunRequest(resume_interrupted=True, improvement_decision="stop_and_report"),
            "resume_interrupted",
            "Codex 正在后台恢复任务执行。",
        ),
        (
            TaskRunRequest(resume_after_human=True, plan_text="1. Train and validate a small baseline."),
            "resume_after_human",
            "Codex 正在后台接收人工确认并继续执行。",
        ),
    ],
)
def test_run_task_async_continue_returns_before_codex_continue(
    monkeypatch: pytest.MonkeyPatch,
    payload: TaskRunRequest,
    action: str,
    note: str,
) -> None:
    task = _task()
    task.status = TaskStatus.paused_for_review
    task.codex_workspace_path = "D:/runs/task"
    saved_tasks: list[TaskRecord] = []

    class Store:
        def get_task(self, team_id: str, task_id: str, *, access_token: str) -> TaskRecord | None:
            return task

        def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
            saved_tasks.append(task)
            return task

    class HumanService:
        def assert_task_can_run(self, task: TaskRecord, *, access_token: str) -> None:
            return None

    def fail_if_called(*args: object, **kwargs: object) -> TaskRecord:
        raise AssertionError("Codex continue path was called before the response returned.")

    monkeypatch.setattr("backend.app.api.routes.task_run.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.api.routes.task_run.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.api.routes.task_run.assert_task_run_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run._assert_codex_task_can_control_current_activity", lambda task, team_access: task)
    monkeypatch.setattr("backend.app.api.routes.task_run._assert_quota_allows_action", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run.get_task_human_collaboration_service", lambda: HumanService())
    monkeypatch.setattr("backend.app.api.routes.task_run.record_codex_running_stages", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run._regenerate_codex_plan_and_save", fail_if_called)
    monkeypatch.setattr("backend.app.api.routes.task_run._resume_interrupted_codex_task", fail_if_called)
    monkeypatch.setattr("backend.app.api.routes.task_run._approve_codex_plan_and_save", fail_if_called)

    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )
    background_tasks = BackgroundTasks()

    result = run_task(
        task.id,
        payload,
        team_access,
        background_tasks=background_tasks,
        async_start=True,
    )

    queued_call = background_tasks.tasks[0]
    assert result.status == TaskStatus.running
    assert result.codex_status == "starting"
    assert result.notes == note
    assert saved_tasks == [result]
    assert len(background_tasks.tasks) == 1
    assert queued_call.args[0] == action
    assert queued_call.args[1].status == TaskStatus.paused_for_review
    assert queued_call.args[2] == payload


def test_run_task_async_resume_requires_improvement_decision_for_waiting_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    task.status = TaskStatus.paused_for_review
    task.codex_workspace_path = "D:/runs/task"

    class Store:
        def get_task(self, team_id: str, task_id: str, *, access_token: str) -> TaskRecord | None:
            return task

    class HumanService:
        def assert_task_can_run(self, task: TaskRecord, *, access_token: str) -> None:
            return None

    monkeypatch.setattr("backend.app.api.routes.task_run.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.api.routes.task_run.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.api.routes.task_run.assert_task_run_preflight", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run._assert_codex_task_can_control_current_activity", lambda task, team_access: task)
    monkeypatch.setattr("backend.app.api.routes.task_run._assert_quota_allows_action", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.app.api.routes.task_run.get_task_human_collaboration_service", lambda: HumanService())
    monkeypatch.setattr(
        "backend.app.api.routes.task_run.sync_codex_task_state",
        lambda task_arg, settings, **kwargs: (
            task_arg.model_copy(update={"codex_status": "waiting_improvement_review"}),
            {"progress": {"status": "waiting_improvement_review"}},
        ),
    )

    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    with pytest.raises(HTTPException) as raised:
        run_task(
            task.id,
            TaskRunRequest(resume_interrupted=True),
            team_access,
            background_tasks=BackgroundTasks(),
            async_start=True,
        )

    assert raised.value.status_code == status.HTTP_409_CONFLICT
    assert raised.value.detail == "当前任务正在等待改进确认，请先选择继续改进或按当前结果生成报告。"
