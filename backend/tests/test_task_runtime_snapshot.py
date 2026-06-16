from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.models.task import (
    DatasetProfile,
    RunSummary,
    TaskRecord,
    TaskRuntimeSummaryRecord,
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


def test_runtime_snapshot_sync_reads_authoritative_task_before_codex_sync(monkeypatch) -> None:
    task = _task()
    task.executor_type = "codex"
    task.codex_workspace_path = "D:/workspaces/task-runtime-snapshot"
    task.codex_status = "waiting_plan_approval"
    get_task_kwargs = []

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert team_id == "team-1"
            assert task_id == task.id
            get_task_kwargs.append(kwargs)
            return task

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr(
        "backend.app.services.task_runtime_snapshot.sync_codex_runtime_snapshot",
        lambda task_store, task_arg, team_access, settings: (task_arg, None, {}, {}),
    )
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
    assert get_task_kwargs[0]["prefer_cache"] is False
    assert get_task_kwargs[0]["allow_stale_cache"] is False


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


def test_runtime_snapshot_sync_false_skips_codex_io(monkeypatch) -> None:
    task = _task()
    task.executor_type = "codex"
    task.codex_workspace_path = "D:/workspaces/task-runtime-snapshot"
    task.codex_status = "running"
    task.codex_session_id = "session-1"

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert team_id == "team-1"
            assert task_id == task.id
            return task

    def fail_if_called(*args, **kwargs):
        raise AssertionError("sync=false snapshot must not touch Codex runtime or workspace IO")

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.sync_codex_runtime_snapshot", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.safe_reconcile_codex_runtime_activity", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.build_codex_run_progress", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.read_codex_artifacts", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.codex_plan_text", fail_if_called)
    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    response = build_task_runtime_snapshot_response(task.id, team_access, sync_runtime=False)

    assert response.task.id == task.id
    assert response.task_run["codex"]["workspace_path"] == task.codex_workspace_path
    assert response.task_run["codex"]["plan_text"] == ""
    assert response.task_run["progress_percent"] == 58
    assert response.task_run["progress_source"] == "stage_status"


def test_completed_runtime_snapshot_sync_false_reads_known_codex_summary_artifacts(tmp_path, monkeypatch) -> None:
    task = _task()
    task.status = TaskStatus.completed
    task.executor_type = "codex"
    workspace = tmp_path / "ai4ml-task-runtime-snapshot"
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "metrics.json").write_text(
        json.dumps(
            {
                "final_model": {"name": "LogisticRegression", "validation_accuracy": 0.9333333333},
                "candidate_models": {
                    "LogisticRegression": {"validation_accuracy": 0.9333333333},
                    "RandomForest": {"validation_accuracy": 0.9},
                },
                "feature_importance": [{"feature": "age", "importance": 0.8}],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "overview.json").write_text(
        json.dumps({"task_summary": {"conclusion": "真实产物已生成。"}}),
        encoding="utf-8",
    )
    (output_dir / "token_usage.json").write_text(
        json.dumps({"total": {"total_tokens": 123}}),
        encoding="utf-8",
    )
    task.codex_workspace_path = str(workspace)

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert team_id == "team-1"
            assert task_id == task.id
            return task

    def fail_if_called(*args, **kwargs):
        raise AssertionError("completed sync=false snapshot must not call live Codex sync")

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr(
        "backend.app.services.task_runtime_snapshot.get_settings",
        lambda: SimpleNamespace(codex_workspace_root=tmp_path, storage_dir=tmp_path / "tasks"),
    )
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.sync_codex_runtime_snapshot", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.safe_reconcile_codex_runtime_activity", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.build_codex_run_progress", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.read_codex_artifacts", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.codex_plan_text", fail_if_called)
    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    response = build_task_runtime_snapshot_response(task.id, team_access, sync_runtime=False)

    assert response.task_run["metrics"] == {"accuracy": 0.9333333333}
    assert response.task_run["leaderboard"][0]["model"] == "LogisticRegression"
    assert response.task_run["overview"]["task_summary"]["conclusion"] == "真实产物已生成。"
    assert response.task_run["codex"]["token_usage"] == {"total": {"total_tokens": 123}}


def test_completed_runtime_snapshot_sync_true_uses_lightweight_summary_artifacts(tmp_path, monkeypatch) -> None:
    task = _task()
    task.status = TaskStatus.completed
    task.executor_type = "codex"
    workspace = tmp_path / "ai4ml-task-runtime-snapshot"
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True)
    (workspace / "input").mkdir()
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({"authoritative_inputs": {"task_id": task.id}}),
        encoding="utf-8",
    )
    (output_dir / "metrics.json").write_text(
        json.dumps({"selected_model": {"name": "RandomForest", "validation_rmse": 0.3679}}),
        encoding="utf-8",
    )
    (output_dir / "overview.json").write_text(
        json.dumps({"task_summary": {"conclusion": "完成态轻量读取。"}}),
        encoding="utf-8",
    )
    (output_dir / "token_usage.json").write_text(
        json.dumps({"total": {"total_tokens": 638727}}),
        encoding="utf-8",
    )
    task.codex_workspace_path = str(workspace)
    saved_tasks = []

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert kwargs["prefer_cache"] is False
            assert kwargs["allow_stale_cache"] is False
            assert team_id == "team-1"
            assert task_id == task.id
            return task

        def save_task(self, task_arg, **kwargs):
            assert kwargs["access_token"] == "token"
            saved_tasks.append(task_arg.model_copy(deep=True))
            return task_arg

    def fail_if_called(*args, **kwargs):
        raise AssertionError("completed sync=true snapshot must not call full live Codex sync")

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr(
        "backend.app.services.task_runtime_snapshot.get_settings",
        lambda: SimpleNamespace(codex_workspace_root=tmp_path, storage_dir=tmp_path / "tasks"),
    )
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.sync_codex_runtime_snapshot", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.safe_reconcile_codex_runtime_activity", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.build_codex_run_progress", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.read_codex_artifacts", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.codex_plan_text", fail_if_called)
    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    response = build_task_runtime_snapshot_response(task.id, team_access, sync_runtime=True)

    assert response.task.status == TaskStatus.completed
    assert response.task_run["progress_percent"] == 100
    assert response.task.last_run is not None
    assert response.task_run["metrics"] == {"rmse": 0.3679}
    assert response.task_run["overview"]["task_summary"]["conclusion"] == "完成态轻量读取。"
    assert response.task_run["codex"]["token_usage"] == {"total": {"total_tokens": 638727}}
    assert len(saved_tasks) == 1
    assert saved_tasks[0].last_run is not None
    assert saved_tasks[0].last_run.metric_name == "rmse"


def test_completed_runtime_snapshot_sync_false_derives_overview_from_last_run_when_workspace_missing(
    monkeypatch,
) -> None:
    task = _task()
    task.status = TaskStatus.completed
    task.executor_type = "codex"
    task.codex_workspace_path = "/opt/ai4ml/app/codex_use/workspaces/ai4ml-missing"
    task.last_run = RunSummary(
        best_model="ridge_ohe",
        metric_name="signed_log_mae",
        metric_value=0.492564,
        output_dir="/opt/ai4ml/app/codex_use/workspaces/ai4ml-missing",
    )

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert team_id == "team-1"
            assert task_id == task.id
            return task

    def fail_if_called(*args, **kwargs):
        raise AssertionError("completed sync=false missing-workspace fallback must not call live Codex sync")

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr(
        "backend.app.services.task_runtime_snapshot.get_settings",
        lambda: SimpleNamespace(codex_workspace_root="/missing"),
    )
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.sync_codex_runtime_snapshot", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.safe_reconcile_codex_runtime_activity", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.build_codex_run_progress", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.read_codex_artifacts", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.codex_plan_text", fail_if_called)
    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    response = build_task_runtime_snapshot_response(task.id, team_access, sync_runtime=False)

    assert response.task_run["metrics"] == {"signed_log_mae": 0.492564}
    assert response.task_run["overview"]["prediction_error"]["primary_metric"] == "signed_log_mae"
    assert response.task_run["overview"]["result_checks"][0]["name"] == "artifact_access"


def test_runtime_snapshot_summary_omits_large_task_detail_fields(monkeypatch) -> None:
    task = _task()
    task.executor_type = "codex"
    task.codex_workspace_path = "D:/workspaces/task-runtime-snapshot"
    task.codex_status = "waiting_plan_approval"
    task.codex_session_id = "session-1"
    task.structured_requirements = {
        "selected_plan": {"plan_text": "x" * 5000},
        "target_definition": {"target_columns": ["label"]},
    }
    task.dataset_profile = DatasetProfile(
        filename="dataset.csv",
        path="D:/datasets/dataset.csv",
        row_count=100,
        column_count=2,
        columns=[],
        preview_rows=[{"feature": "1", "label": "0"}],
        generated_at=datetime.now(timezone.utc),
    )

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert team_id == "team-1"
            assert task_id == task.id
            return task

    def fail_if_called(*args, **kwargs):
        raise AssertionError("summary sync=false snapshot must not touch Codex runtime or workspace IO")

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_settings", lambda: object())
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.sync_codex_runtime_snapshot", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.safe_reconcile_codex_runtime_activity", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.build_codex_run_progress", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.read_codex_artifacts", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.codex_plan_text", fail_if_called)
    team_access = SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )

    response = build_task_runtime_snapshot_response(
        task.id,
        team_access,
        sync_runtime=False,
        task_detail="summary",
    )
    payload = response.model_dump(mode="json")

    assert isinstance(response.task, TaskRuntimeSummaryRecord)
    assert payload["task"]["id"] == task.id
    assert payload["task"]["codex_workspace_path"] == task.codex_workspace_path
    assert "structured_requirements" not in payload["task"]
    assert "dataset_profile" not in payload["task"]
    assert "interaction_policies" not in payload["task"]


def test_stop_and_report_completed_snapshot_keeps_completed_state(tmp_path, monkeypatch) -> None:
    task = _task()
    task.status = TaskStatus.running
    task.executor_type = "codex"
    workspace = tmp_path / "ai4ml-task-runtime-snapshot"
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True)
    (workspace / "input").mkdir()
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({"authoritative_inputs": {"task_id": task.id}}),
        encoding="utf-8",
    )
    (output_dir / "progress.json").write_text(
        json.dumps(
            {
                "status": "partial",
                "current_step": "stop_and_report_completed",
                "summary": "用户选择停止继续改进，已生成当前结果报告。",
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "metrics.json").write_text(
        json.dumps(
            {
                "selected_model": {"name": "LogisticRegression", "validation_accuracy": 0.9333333333},
                "acceptance": {"passed": False},
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "overview.json").write_text(
        json.dumps({"task_summary": {"conclusion": "未达标但已收尾。"}}),
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (output_dir / "predict.py").write_text("print('predict')\n", encoding="utf-8")
    task.codex_workspace_path = str(workspace)

    class Store:
        def get_task(self, team_id, task_id, **kwargs):
            assert kwargs["prefer_cache"] is False
            assert kwargs["allow_stale_cache"] is False
            assert team_id == "team-1"
            assert task_id == task.id
            return task

        def save_task(self, task_arg, **kwargs):
            assert kwargs["access_token"] == "token"
            return task_arg

    def fail_if_called(*args, **kwargs):
        raise AssertionError("stop-and-report completed snapshot must not be reconciled as interrupted")

    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.get_task_store", lambda: Store())
    monkeypatch.setattr(
        "backend.app.services.task_runtime_snapshot.get_settings",
        lambda: SimpleNamespace(codex_workspace_root=tmp_path, storage_dir=tmp_path / "tasks"),
    )
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.is_codex_task", lambda task_arg, settings: True)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.safe_reconcile_codex_runtime_activity", fail_if_called)
    monkeypatch.setattr("backend.app.services.task_runtime_snapshot.codex_plan_text", lambda task_arg, settings: "")

    response = build_task_runtime_snapshot_response(
        task.id,
        SimpleNamespace(team_id="team-1", access_token="token", user=SimpleNamespace(id="user-1")),
        sync_runtime=True,
    )

    assert response.task.status == TaskStatus.completed
    assert response.task.codex_status == "completed"
    assert response.task_run["progress_status"] == "completed"
    assert response.task_run["progress_percent"] == 100
    assert response.task_run["current_stage"] == WorkflowStage.report_generation.value
