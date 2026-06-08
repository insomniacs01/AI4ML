from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskAgentRecord,
    TaskHumanRequestRecord,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.task_agent_events import build_task_agent_events


def test_build_task_agent_events_skips_inactive_pending_agents_and_sorts_requests() -> None:
    now = datetime.now(timezone.utc)
    older = now - timedelta(minutes=1)
    agents = [
        TaskAgentRecord(
            id=WorkflowStage.data_analysis.value,
            stage=WorkflowStage.data_analysis,
            name="数据检查",
            role="分析数据",
            short_role="数据",
            status=WorkflowStageStatus.completed,
            current_task="数据画像完成",
            last_action_at=older,
            artifact_refs=["output/profile.json"],
        ),
        TaskAgentRecord(
            id=WorkflowStage.model_selection.value,
            stage=WorkflowStage.model_selection,
            name="模型选择",
            role="选择模型",
            short_role="模型",
            status=WorkflowStageStatus.pending,
            current_task="等待上游",
            last_action_at=None,
        ),
    ]
    request = TaskHumanRequestRecord(
        id="request-1",
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.training_validation,
        status=HumanInteractionRequestStatus.open,
        payload={"request_type": "metric_review", "artifact_paths": {"report": "output/report.md"}},
        created_at=now,
        updated_at=now,
    )

    events = build_task_agent_events(agents, [request])

    assert [event.id for event in events] == ["request-request-1", f"stage-data_analysis-{older.isoformat()}"]
    assert events[0].text == "人工确认 metric_review 当前状态：open"
    assert events[0].artifact_refs == ["report: output/report.md"]
    assert events[1].text == "数据检查（分析数据）已完成：数据画像完成"


def test_build_task_agent_events_prefers_payload_title() -> None:
    now = datetime.now(timezone.utc)
    request = TaskHumanRequestRecord(
        id="request-2",
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.data_analysis,
        status=HumanInteractionRequestStatus.confirmed,
        payload={"title": "确认数据字段", "request_type": "field_review"},
        created_at=now,
        updated_at=now,
    )

    events = build_task_agent_events([], [request])

    assert events[0].text == "人工确认 确认数据字段 当前状态：confirmed"
