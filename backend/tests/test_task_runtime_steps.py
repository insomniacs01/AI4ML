from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.models.task import TaskRecord, TaskStatus, TaskStepSummaryRecord, WorkflowStage, WorkflowStageStatus
from backend.app.services.task_runtime_steps import build_runtime_steps, progress_from_steps


def _task(status: TaskStatus = TaskStatus.running) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-runtime-steps",
        team_id="team-1",
        created_by="user-1",
        name="Runtime Steps Task",
        description="Project runtime steps.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_build_runtime_steps_maps_paused_codex_interruption_to_waiting_human() -> None:
    progress = SimpleNamespace(
        status="blocked",
        task_status=TaskStatus.paused_for_review,
        codex_raw_steps=[
            {
                "id": "plan",
                "title": "Approve plan",
                "status": "interrupted",
                "detail": "waiting for approval",
                "artifacts": ["output/plan.md"],
            }
        ],
    )

    steps = build_runtime_steps(_task(TaskStatus.paused_for_review), [], progress)

    assert len(steps) == 1
    assert steps[0].id == "plan"
    assert steps[0].status == WorkflowStageStatus.waiting_human.value
    assert steps[0].message == "waiting for approval"
    assert steps[0].artifacts == ["output/plan.md"]


def test_build_runtime_steps_applies_progress_activity_and_training_metric_summary() -> None:
    progress = SimpleNamespace(
        status="running",
        current_stage=WorkflowStage.model_selection,
        current_activity="Selecting candidate models",
        artifacts=SimpleNamespace(metric_name="mae", metric_value=2.5, best_model="ridge"),
        codex_raw_steps=[],
    )

    steps = build_runtime_steps(_task(), [], progress)
    by_name = {step.name: step for step in steps}

    assert by_name[WorkflowStage.model_selection.value].status == WorkflowStageStatus.running.value
    assert by_name[WorkflowStage.model_selection.value].message == "Selecting candidate models"
    assert by_name[WorkflowStage.training_validation.value].summary == "mae: 2.5；最佳模型: ridge"


def test_progress_from_steps_uses_running_step_stage_percent() -> None:
    steps = [
        TaskStepSummaryRecord(
            id="requirement_analysis",
            name=WorkflowStage.requirement_analysis.value,
            node=WorkflowStage.requirement_analysis.value,
            title="需求解析",
            agent_role="需求解析",
            status=WorkflowStageStatus.completed.value,
        ),
        TaskStepSummaryRecord(
            id="model_selection",
            name=WorkflowStage.model_selection.value,
            node=WorkflowStage.model_selection.value,
            title="模型选择",
            agent_role="模型选择",
            status=WorkflowStageStatus.running.value,
            message="Selecting candidate models",
        ),
        TaskStepSummaryRecord(
            id="training_validation",
            name=WorkflowStage.training_validation.value,
            node=WorkflowStage.training_validation.value,
            title="训练验证",
            agent_role="训练验证",
            status=WorkflowStageStatus.pending.value,
        ),
    ]

    progress = progress_from_steps(_task(TaskStatus.running), steps)

    assert progress == {
        "status": "running",
        "progress_percent": 50,
        "progress_source": "stage_status",
        "progress_unavailable_reason": None,
        "current_stage": WorkflowStage.model_selection.value,
        "current_activity": "Selecting candidate models",
    }


def test_progress_from_steps_preserves_waiting_step_detail_for_blocked_task() -> None:
    steps = [
        TaskStepSummaryRecord(
            id="training_validation",
            name=WorkflowStage.training_validation.value,
            node=WorkflowStage.training_validation.value,
            title="训练验证",
            agent_role="训练验证",
            status=WorkflowStageStatus.waiting_human.value,
            message="Review the selected model",
        )
    ]

    progress = progress_from_steps(_task(TaskStatus.paused_for_review), steps)

    assert progress == {
        "status": "blocked",
        "progress_percent": 50,
        "progress_source": "stage_status",
        "progress_unavailable_reason": None,
        "current_stage": WorkflowStage.training_validation.value,
        "current_activity": "Review the selected model",
    }


def test_progress_from_steps_does_not_invent_progress_for_startable_task() -> None:
    steps = [
        TaskStepSummaryRecord(
            id="data_analysis",
            name=WorkflowStage.data_analysis.value,
            node=WorkflowStage.data_analysis.value,
            title="数据分析",
            agent_role="数据分析",
            status=WorkflowStageStatus.completed.value,
        )
    ]

    progress = progress_from_steps(_task(TaskStatus.uploaded), steps)

    assert progress == {
        "status": "not_started",
        "progress_percent": 0,
        "current_stage": WorkflowStage.data_analysis.value,
    }


def test_progress_from_steps_never_reports_failed_task_as_100_percent() -> None:
    steps = [
        TaskStepSummaryRecord(
            id="requirement_analysis",
            name=WorkflowStage.requirement_analysis.value,
            node=WorkflowStage.requirement_analysis.value,
            title="需求解析",
            agent_role="需求解析",
            status=WorkflowStageStatus.completed.value,
        ),
        TaskStepSummaryRecord(
            id="training_validation",
            name=WorkflowStage.training_validation.value,
            node=WorkflowStage.training_validation.value,
            title="训练验证",
            agent_role="训练验证",
            status=WorkflowStageStatus.failed.value,
            message="Training failed",
        ),
    ]

    progress = progress_from_steps(_task(TaskStatus.failed), steps)

    assert progress == {
        "status": "failed",
        "progress_percent": 75,
        "progress_source": "stage_status",
        "progress_unavailable_reason": None,
        "current_stage": WorkflowStage.training_validation.value,
        "current_activity": "Training failed",
    }


def test_progress_from_steps_reports_cancelled_task_without_full_completion() -> None:
    progress = progress_from_steps(_task(TaskStatus.cancelled), [])

    assert progress == {
        "status": "cancelled",
        "progress_percent": None,
        "progress_source": None,
        "progress_unavailable_reason": "progress_percent_missing",
        "current_stage": None,
        "current_activity": "",
    }
