from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import WorkflowStage
from backend.app.services.codex_progress_timeline import (
    build_codex_progress_events,
    build_codex_progress_insights,
    workflow_stage_from_codex_step,
)


def test_codex_progress_events_prefer_jsonl_events_and_keep_last_80() -> None:
    artifacts = {
        "progress_events": [
            {
                "event": f"event_{index}",
                "step": "model_validation",
                "message": f"message {index}",
                "ts": "2026-01-01T00:00:00Z",
            }
            for index in range(81)
        ]
    }

    events = build_codex_progress_events({"steps": [{"id": "report", "status": "completed"}]}, artifacts)

    assert len(events) == 80
    assert events[0].event_type == "event_1"
    assert events[-1].event_type == "event_80"
    assert events[-1].stage == WorkflowStage.training_validation
    assert events[-1].time == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert events[-1].source == "codex_progress_event"


def test_codex_progress_events_fall_back_to_steps_and_plan() -> None:
    events = build_codex_progress_events(
        {
            "steps": [
                {"id": "feature_generation", "title": "Feature build", "status": "running", "detail": "encoding"},
                "invalid",
            ]
        },
        {},
    )

    assert len(events) == 1
    assert events[0].stage == WorkflowStage.feature_engineering
    assert events[0].event_type == "running"
    assert events[0].message == "Feature build: encoding"
    assert events[0].source == "codex_progress"

    plan_events = build_codex_progress_events({}, {"plan": {"exists": True}})
    assert len(plan_events) == 1
    assert plan_events[0].stage == WorkflowStage.data_analysis
    assert plan_events[0].event_type == "plan_ready"
    assert plan_events[0].source == "codex_workspace"


def test_codex_progress_insights_use_status_severity_and_workspace_evidence() -> None:
    insights = build_codex_progress_insights(
        {"status": "plan_ready"},
        {"plan": {"exists": True}, "workspace": {"path": "D:/workspaces/task-1"}},
    )

    assert len(insights) == 1
    assert insights[0].event_type == "codex_plan_ready"
    assert insights[0].severity == "warning"
    assert insights[0].detail == "计划文件已生成，等待确认。"
    assert insights[0].evidence == "D:/workspaces/task-1"
    assert insights[0].stage == WorkflowStage.data_analysis


def test_workflow_stage_from_codex_step_uses_stable_keyword_mapping() -> None:
    assert workflow_stage_from_codex_step("final_report") == WorkflowStage.report_generation
    assert workflow_stage_from_codex_step("train_model") == WorkflowStage.training_validation
    assert workflow_stage_from_codex_step("feature_selection") == WorkflowStage.feature_engineering
    assert workflow_stage_from_codex_step("workspace_initialized") == WorkflowStage.data_analysis
