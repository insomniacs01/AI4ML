from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskAgentRecord,
    TaskAgentMessageRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.task_agent_collaboration import _build_events, append_stage_agent_messages, build_task_agent_collaboration_response


class _FakeTaskStore:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.calls: list[dict] = []

    def append_agent_message(self, **payload):
        self.calls.append(payload)
        return TaskAgentMessageRecord(
            id=f"message-{len(self.calls)}",
            team_id=payload["team_id"],
            task_id=payload["task_id"],
            from_agent_id=payload["from_agent_id"],
            to_agent_id=payload.get("to_agent_id"),
            stage=payload["stage"],
            message_type=payload["message_type"],
            status=payload["status"],
            content=payload["content"],
            payload=payload["payload"],
            artifact_refs=payload["payload"]["artifact_refs"],
            correlation_id=payload["correlation_id"],
            time=self.now,
        )


def test_agent_collaboration_hides_raw_runtime_text() -> None:
    now = datetime.now(timezone.utc)
    task = TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Agent Task",
        description="Train a model.",
        status=TaskStatus.failed,
        created_at=now,
        updated_at=now,
    )
    raw_runtime_text = "Traceback (most recent call last): C:\\workspace\\very\\long\\path\\run.py failed"
    stage = WorkflowStageRecord(
        id="stage-1",
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.training_validation,
        status=WorkflowStageStatus.failed,
        summary=raw_runtime_text,
        log_excerpt=raw_runtime_text,
        created_at=now,
        updated_at=now,
    )
    message = TaskAgentMessageRecord(
        id="message-1",
        team_id="team-1",
        task_id="task-1",
        from_agent_id=WorkflowStage.training_validation.value,
        stage=WorkflowStage.training_validation,
        message_type="blocker",
        status="sent",
        content=raw_runtime_text,
        payload={"summary": raw_runtime_text, "log_excerpt": raw_runtime_text},
        time=now,
    )

    response = build_task_agent_collaboration_response(
        task,
        stages=[stage],
        requests=[],
        agent_messages=[message],
    )

    assert response.stages[0].summary == "训练或验证失败，系统已保留报错文件并等待诊断。"
    assert response.stages[0].log_excerpt is None
    training_agent = next(agent for agent in response.agents if agent.id == WorkflowStage.training_validation.value)
    assert training_agent.current_task == "训练或验证失败，系统已保留报错文件并等待诊断。"
    assert "Traceback" not in response.events[0].text
    assert response.messages[0].content == "系统已隐藏原始运行日志；请查看诊断结论或报错文件。"
    assert response.messages[0].payload == {"summary": None, "log_excerpt": None}


def test_build_events_skips_inactive_pending_agents_and_sorts_requests() -> None:
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

    events = _build_events(agents, [request])

    assert [event.id for event in events] == ["request-request-1", f"stage-data_analysis-{older.isoformat()}"]
    assert events[0].text == "人工确认 metric_review 当前状态：open"
    assert events[0].artifact_refs == ["report: output/report.md"]
    assert events[1].text == "数据检查（分析数据）已完成：数据画像完成"


def test_append_stage_agent_messages_records_handoff_and_acknowledgement() -> None:
    now = datetime.now(timezone.utc)
    task = TaskRecord(
        id="task-2",
        team_id="team-1",
        created_by="user-1",
        name="Agent Messages Task",
        description="Train a model.",
        status=TaskStatus.running,
        created_at=now,
        updated_at=now,
    )
    store = _FakeTaskStore(now)

    messages = append_stage_agent_messages(
        store,
        task,
        access_token="token-1",
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.completed,
        summary="数据画像完成",
        artifact_refs={"profile": ["output/profile.json"], "report": "output/report.md"},
        log_excerpt="ok",
    )

    assert [message.message_type for message in messages] == ["handoff", "acknowledgement"]
    assert messages[0].from_agent_id == WorkflowStage.data_analysis.value
    assert messages[0].to_agent_id == WorkflowStage.feature_engineering.value
    assert messages[0].payload["message_type_label"] == "阶段交接"
    assert messages[0].payload["artifact_count"] == 2
    assert messages[0].payload["artifact_refs"] == ["output/profile.json", "report: output/report.md"]
    assert messages[0].content == "数据检查 已完成“检查数据”，向 数据处理 交接：数据画像完成 已附带 2 个真实文件引用。"
    assert messages[1].from_agent_id == WorkflowStage.feature_engineering.value
    assert messages[1].to_agent_id == WorkflowStage.data_analysis.value
    assert messages[1].payload["message_type_label"] == "接收确认"
    assert all(message.correlation_id.startswith("agent-msg:") for message in messages)
