from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.models.task import (
    RunSummary,
    TaskRecord,
    TaskRunProgressArtifactSummary,
    TaskRunProgressLeaderboardRow,
    TaskRunProgressResponse,
    TaskStatus,
    TaskStepSummaryRecord,
    WorkflowStage,
)
from backend.app.services.task_runtime_snapshot import (
    TaskRuntimeSnapshotSyncError,
    build_task_runtime_snapshot_response,
)
from backend.app.services.task_codex_runtime_activity import reconcile_codex_runtime_activity
from backend.app.services.task_runtime_snapshot_payload import build_task_run_payload


def _task() -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-runtime-snapshot",
        team_id="team-1",
        created_by="user-1",
        name="Runtime Snapshot Task",
        description="Build runtime snapshot payload.",
        status=TaskStatus.running,
        created_at=now,
        updated_at=now,
    )


def _step() -> TaskStepSummaryRecord:
    return TaskStepSummaryRecord(
        id="training_validation",
        name=WorkflowStage.training_validation.value,
        node="training_validation",
        title="训练验证",
        agent_role="Model trainer",
        status="running",
        message="Training models",
    )


def test_task_run_payload_uses_last_run_fields_without_codex_progress() -> None:
    task = _task()
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.5,
        validation_score=-2.5,
        leaderboard=[{"model": "ridge", "validation_score": -2.5}],
        output_dir="D:/runs/task-runtime-snapshot",
    )

    payload = build_task_run_payload(
        task,
        [_step()],
        None,
        {
            "progress_percent": 66,
            "current_stage": WorkflowStage.training_validation.value,
            "current_activity": "Training models",
            "status": "running",
        },
        {"summary": "overview"},
        should_sync_codex=False,
        codex_plan="",
    )

    assert payload["steps"][0]["id"] == "training_validation"
    assert payload["leaderboard"] == [{"model": "ridge", "validation_score": -2.5}]
    assert payload["metrics"] == {"mae": 2.5}
    assert payload["progress_percent"] == 66
    assert payload["current_stage"] == WorkflowStage.training_validation.value
    assert payload["current_activity"] == "Training models"
    assert payload["progress_status"] == "running"
    assert payload["codex"] is None


def test_task_run_payload_prefers_codex_progress_fields() -> None:
    task = _task()
    task.codex_workspace_path = "D:/workspaces/fallback"
    task.codex_session_id = "session-1"
    task.codex_thread_id = "thread-1"
    task.codex_status = "running"
    progress_response = TaskRunProgressResponse(
        task=task,
        status="running",
        progress_percent=42,
        current_stage=WorkflowStage.model_selection,
        current_activity="Selecting models",
        artifacts=TaskRunProgressArtifactSummary(has_run_summary=True, best_model="ridge"),
        leaderboard=[TaskRunProgressLeaderboardRow(model="ridge", validation_score=0.91)],
        codex_raw_progress={"status": "running"},
        codex_raw_steps=[{"id": "model_selection", "status": "running"}],
        codex_workspace_path="D:/workspaces/current",
    )

    payload = build_task_run_payload(
        task,
        [_step()],
        progress_response,
        {
            "progress_percent": 10,
            "current_stage": WorkflowStage.data_analysis.value,
            "current_activity": "Fallback activity",
            "status": "not_started",
        },
        {"checks": [{"id": "plan"}]},
        should_sync_codex=True,
        codex_plan="Approved plan",
    )

    assert payload["leaderboard"] == progress_response.leaderboard
    assert payload["artifacts"]["has_run_summary"] is True
    assert payload["progress_percent"] == 42
    assert payload["current_stage"] == WorkflowStage.model_selection.value
    assert payload["current_activity"] == "Selecting models"
    assert payload["progress_status"] == "running"
    assert payload["codex"] == {
        "workspace_path": "D:/workspaces/current",
        "session_id": "session-1",
        "thread_id": "thread-1",
        "plan_text": "Approved plan",
        "progress": {"status": "running"},
        "steps": [{"id": "model_selection", "status": "running"}],
        "status": "running",
    }


def test_task_run_payload_exposes_codex_artifact_context() -> None:
    task = _task()
    task.codex_workspace_path = "D:/workspaces/current"
    task.codex_status = "waiting_improvement_review"
    events = [{"index": index} for index in range(100)]

    payload = build_task_run_payload(
        task,
        [_step()],
        None,
        {"status": "blocked"},
        {},
        should_sync_codex=True,
        codex_plan="Approved plan",
        codex_artifacts={
            "progress_events": events,
            "progress_events_file": {"exists": True, "path": "state/progress_events.jsonl"},
            "improvement_plan": "Improve validation.",
            "improvement_plan_file": {"exists": True, "path": "output/improvement_plan.md"},
            "token_usage": {"total": {"total_tokens": 123}},
        },
    )

    codex = payload["codex"]
    assert codex["progress_events"] == events[-80:]
    assert codex["progress_events_path"] == "state/progress_events.jsonl"
    assert codex["improvement_plan_text"] == "Improve validation."
    assert codex["improvement_plan_path"] == "output/improvement_plan.md"
    assert codex["token_usage"] == {"total": {"total_tokens": 123}}


def test_reconcile_codex_runtime_activity_pauses_inactive_running_task(monkeypatch) -> None:
    task = _task()
    task.executor_type = "codex"
    task.codex_status = "running"
    task.codex_session_id = "session-1"
    saved_tasks = []

    class Store:
        def save_task(self, task_to_save, access_token=None):
            saved_tasks.append((task_to_save, access_token))
            return task_to_save

    team_access = type("TeamAccess", (), {"access_token": "token"})()
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_activity.fetch_codex_task_status",
        lambda task_arg, settings: {"running": False, "progressStatus": "interrupted"},
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_activity.sync_codex_task_state",
        lambda task_arg, settings, **kwargs: (task_arg, {}),
    )

    reconciled = reconcile_codex_runtime_activity(Store(), task, team_access, object())

    assert reconciled.status == TaskStatus.paused_for_review
    assert reconciled.codex_status == "interrupted"
    assert "没有运行中的执行轮次" in reconciled.notes
    assert saved_tasks[0][1] == "token"


def test_reconcile_codex_runtime_activity_returns_display_state_when_save_fails(monkeypatch) -> None:
    task = _task()
    task.executor_type = "codex"
    task.codex_status = "running"
    task.codex_session_id = "session-1"

    class Store:
        def save_task(self, task_to_save, access_token=None):
            raise RuntimeError("database unavailable")

    team_access = type("TeamAccess", (), {"access_token": "token"})()
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_activity.fetch_codex_task_status",
        lambda task_arg, settings: {"running": False, "progressStatus": "interrupted"},
    )
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_activity.sync_codex_task_state",
        lambda task_arg, settings, **kwargs: (task_arg, {}),
    )

    reconciled = reconcile_codex_runtime_activity(Store(), task, team_access, object())

    assert reconciled.status == TaskStatus.paused_for_review
    assert reconciled.codex_status == "interrupted"
    assert "没有运行中的执行轮次" in reconciled.notes


def test_reconcile_codex_runtime_activity_keeps_verified_running_task(monkeypatch) -> None:
    task = _task()
    task.executor_type = "codex"
    task.codex_status = "running"
    task.codex_session_id = "session-1"

    class Store:
        def save_task(self, task_to_save, access_token=None):
            raise AssertionError("verified running task should not be saved")

    team_access = type("TeamAccess", (), {"access_token": "token"})()
    monkeypatch.setattr(
        "backend.app.services.task_codex_runtime_activity.fetch_codex_task_status",
        lambda task_arg, settings: {"running": True, "progressStatus": "running"},
    )

    reconciled = reconcile_codex_runtime_activity(Store(), task, team_access, object())

    assert reconciled.status == TaskStatus.running
    assert reconciled.codex_status == "running"


def test_runtime_snapshot_returns_cached_state_when_codex_sync_fails(monkeypatch) -> None:
    task = _task()
    task.executor_type = "codex"
    task.codex_workspace_path = "D:/workspaces/task-runtime-snapshot"
    task.codex_status = "running"

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert team_id == "team-1"
            assert task_id == task.id
            return task

    def raise_sync_error(*args, **kwargs):
        raise TaskRuntimeSnapshotSyncError("sync write failed")

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.sync_codex_runtime_snapshot", raise_sync_error)
    monkeypatch.setattr(
        "backend.app.services.task_runtime_snapshot.safe_reconcile_codex_runtime_activity",
        lambda task_store, task_arg, team_access, settings: task_arg,
    )
    monkeypatch.setattr(
        "backend.app.services.task_runtime_snapshot.build_codex_run_progress",
        lambda task_arg, settings: None,
    )
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.codex_plan_text", lambda task_arg, settings: "")
    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    response = build_task_runtime_snapshot_response(task.id, team_access, sync_runtime=True)

    assert response.task.id == task.id
    assert response.task_run["codex"]["workspace_path"] == task.codex_workspace_path
