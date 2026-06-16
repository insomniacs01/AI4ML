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


def test_apply_codex_artifact_sync_waiting_improvement_review_overrides_failed_acceptance(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    task = _task()

    synced = apply_codex_artifact_sync(
        task,
        _workspace_artifact(
            tmp_path / "workspace",
            progress={
                "status": "waiting_improvement_review",
                "summary": "结果未达阈值，等待用户选择继续改进或停止。",
            },
            metrics={"acceptance": {"passed": False}},
        ),
        now=now,
    )

    assert synced.status == TaskStatus.paused_for_review
    assert synced.codex_status == "waiting_improvement_review"
    assert synced.codex_finished_at is None
    assert synced.last_run is None
    assert synced.last_run_attempt is not None
    assert synced.last_run_attempt.output_dir == str(tmp_path / "workspace")
    assert synced.last_run_attempt.diagnosis is None
    assert synced.notes == "Codex 已生成改进决策方案，等待用户选择继续改进或按当前结果生成报告。"
    assert synced.structured_requirements["human_loop"]["previous_status"] == TaskStatus.running.value
    assert synced.structured_requirements["codex"]["status"] == "waiting_improvement_review"


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


def test_apply_codex_artifact_sync_unmet_acceptance_waits_for_user_decision(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    task = _task()

    synced = apply_codex_artifact_sync(
        task,
        {
            **_workspace_artifact(
                tmp_path / "workspace",
                progress={"status": "completed", "summary": "final artifacts written"},
                metrics={"acceptance": {"passed": False}},
            ),
            "report": {"exists": True},
            "predict": {"exists": True},
        },
        now=now,
    )

    assert synced.status == TaskStatus.paused_for_review
    assert synced.codex_status == "waiting_improvement_review"
    assert synced.codex_finished_at is None
    assert synced.last_run is None
    assert synced.last_run_attempt is not None
    assert synced.last_run_attempt.output_dir == str(tmp_path / "workspace")
    assert synced.last_run_attempt.diagnosis is None
    assert synced.notes == "当前结果未达到成功标准，等待用户确认继续改进或按当前结果生成报告。"


def test_apply_codex_artifact_sync_stop_and_report_completes_partial_result(tmp_path: Path) -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    task = _task(TaskStatus.paused_for_review)
    task.codex_status = "waiting_improvement_review"

    synced = apply_codex_artifact_sync(
        task,
        {
            **_workspace_artifact(
                tmp_path / "workspace",
                progress={
                    "status": "partial",
                    "current_step": "stop_and_report_completed",
                    "summary": "用户选择停止继续改进，已生成当前结果报告。",
                },
                metrics={
                    "selected_model": {"name": "LogisticRegression", "validation": {"accuracy": 0.9333}},
                    "acceptance": {"passed": False},
                },
            ),
            "overview": {"status": "partial"},
            "report": {"exists": True},
            "predict": {"exists": True},
        },
        now=now,
    )

    assert synced.status == TaskStatus.completed
    assert synced.codex_status == "completed"
    assert synced.codex_finished_at == now
    assert synced.last_run is not None
    assert synced.last_run.best_model == "LogisticRegression"
    assert synced.last_run.metric_name == "accuracy"
    assert synced.last_run.metric_value == 0.9333
    assert synced.notes == "用户选择停止继续改进，已生成当前结果报告。"


def test_apply_codex_artifact_sync_repairs_legacy_failed_unmet_acceptance(tmp_path: Path) -> None:
    task = _task(TaskStatus.failed)
    task.codex_status = "failed"
    task.notes = "旧逻辑误判失败。"

    synced = apply_codex_artifact_sync(
        task,
        {
            **_workspace_artifact(
                tmp_path / "workspace",
                progress={"status": "completed", "summary": "final artifacts written"},
                metrics={"acceptance": {"passed": False}},
            ),
            "report": {"exists": True},
            "predict": {"exists": True},
        },
    )

    assert synced.status == TaskStatus.paused_for_review
    assert synced.codex_status == "waiting_improvement_review"
    assert synced.notes == "当前结果未达到成功标准，等待用户确认继续改进或按当前结果生成报告。"


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
