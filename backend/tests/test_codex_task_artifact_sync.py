from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_task_artifact_sync import apply_codex_artifact_sync


def _task(status: TaskStatus = TaskStatus.running) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Codex Sync Task",
        description="Sync Codex artifacts.",
        status=status,
        executor_type="codex",
        created_at=now,
        updated_at=now,
    )


def _workspace_artifact(workspace: Path, *, progress: dict, metrics: dict | None = None) -> dict:
    return {
        "workspace": {"path": str(workspace), "name": workspace.name},
        "progress": progress,
        "metrics": metrics or {},
    }


def test_apply_codex_artifact_sync_waiting_status_sets_human_loop_and_metadata(tmp_path: Path) -> None:
    task = _task()

    synced = apply_codex_artifact_sync(
        task,
        _workspace_artifact(tmp_path / "workspace", progress={"status": "plan_ready"}),
    )

    assert synced.status == TaskStatus.paused_for_review
    assert synced.codex_status == "plan_ready"
    assert synced.notes == "Codex 已生成建模计划，等待人工确认后继续执行。"
    assert synced.structured_requirements["human_loop"]["previous_status"] == TaskStatus.running.value
    assert synced.structured_requirements["human_loop"]["manual_hold"] is False
    assert synced.structured_requirements["codex"]["workspace_path"] == str(tmp_path / "workspace")
    assert synced.structured_requirements["codex"]["status"] == "plan_ready"


def test_apply_codex_artifact_sync_running_status_records_workspace_attempt_and_token_usage(tmp_path: Path) -> None:
    task = _task()
    artifacts = _workspace_artifact(
        tmp_path / "workspace",
        progress={"status": "running", "summary": "training models"},
    )
    artifacts["token_usage"] = {
        "total": {"input_tokens": 10, "output_tokens": 7, "total_tokens": 17},
    }

    synced = apply_codex_artifact_sync(task, artifacts)

    assert synced.status == TaskStatus.running
    assert synced.codex_workspace_path == str(tmp_path / "workspace")
    assert synced.last_run_attempt is not None
    assert synced.last_run_attempt.output_dir == str(tmp_path / "workspace")
    assert synced.last_run_attempt.token_usage is not None
    assert synced.last_run_attempt.token_usage.total_tokens == 17
    assert synced.notes == "training models"


def test_apply_codex_artifact_sync_completed_artifacts_override_running_progress(tmp_path: Path) -> None:
    output_dir = tmp_path / "workspace" / "output"
    output_dir.mkdir(parents=True)
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    task = _task()

    synced = apply_codex_artifact_sync(
        task,
        {
            **_workspace_artifact(
                tmp_path / "workspace",
                progress={"status": "running", "summary": "still running"},
                metrics={
                    "selected_model": {"name": "ridge", "validation": {"mae": 0.42}},
                    "candidate_models": [{"name": "ridge", "validation": {"mae": 0.42}}],
                },
            ),
            "report": {"exists": True},
            "predict": {"exists": True},
        },
        now=now,
    )

    assert synced.status == TaskStatus.completed
    assert synced.codex_status == "completed"
    assert synced.codex_finished_at == now
    assert synced.last_run is not None
    assert synced.last_run.best_model == "ridge"
    assert synced.last_run.metric_name == "mae"
    assert synced.last_run.metric_value == 0.42
    assert synced.notes == "still running"


def test_apply_codex_artifact_sync_quota_guard_keeps_paused_task_interrupted(tmp_path: Path) -> None:
    task = _task(TaskStatus.paused_for_review)
    task.structured_requirements = {
        "quota_guard": {
            "status": "exhausted",
            "reason": "member_token_quota_exhausted",
        }
    }

    synced = apply_codex_artifact_sync(
        task,
        _workspace_artifact(tmp_path / "workspace", progress={"status": "running"}),
    )

    assert synced.status == TaskStatus.paused_for_review
    assert synced.codex_status == "interrupted"
    assert synced.structured_requirements["quota_guard"]["status"] == "exhausted"
    assert synced.structured_requirements["codex"]["status"] == "interrupted"
