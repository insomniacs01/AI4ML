from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_agent_workflow import build_workflow


def _task(status: TaskStatus = TaskStatus.uploaded) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-agent-workflow",
        team_id="team-1",
        created_by="user-1",
        name="Agent Workflow Task",
        description="Build workflow cards.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_build_workflow_formats_blocked_checklist_baseline_and_failed_modeling() -> None:
    task = _task(TaskStatus.failed)
    task.last_run_attempt = RunAttempt(output_dir="workspace", diagnosis_detail="Training failed after validation.")
    loop = {
        "checklist": [{"status": "passed"}, {"status": "blocked"}],
        "baseline": {
            "status": "completed",
            "label": "mean",
            "metric_name": "mae",
            "metric_value": 2.5,
        },
        "quality_gates": [{"status": "warning", "detail": "Review metric drift."}],
        "next_improvement": {"status": "needs_human_or_retry", "action": "Review selected features."},
    }

    workflow = {step["key"]: step for step in build_workflow(task, loop)}

    assert workflow["task_checklist"]["status"] == "blocked"
    assert workflow["baseline"]["status"] == "completed"
    assert workflow["baseline"]["detail"] == "mean: mae=2.5"
    assert workflow["modeling"]["status"] == "failed"
    assert workflow["modeling"]["detail"] == "Training failed after validation."
    assert workflow["iterative_tuning"]["status"] == "proposed"
    assert workflow["iterative_tuning"]["detail"] == "Review selected features."


def test_build_workflow_marks_modeling_tuning_and_report_completed_after_last_run() -> None:
    task = _task(TaskStatus.completed)
    task.last_run = RunSummary(
        best_model="LightGBM",
        metric_name="accuracy",
        metric_value=0.91,
        output_dir="workspace",
    )

    workflow = {step["key"]: step for step in build_workflow(task, {})}

    assert workflow["modeling"]["status"] == "completed"
    assert workflow["modeling"]["detail"] == "LightGBM: accuracy=0.91"
    assert workflow["iterative_tuning"]["status"] == "completed"
    assert workflow["final_report"]["status"] == "completed"
