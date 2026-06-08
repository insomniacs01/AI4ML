from __future__ import annotations

from backend.app.models.task import WorkflowStageStatus
from backend.app.services.task_agent_status import agent_progress_for_status, agent_status_label


def test_agent_status_label_maps_workflow_stage_statuses() -> None:
    assert agent_status_label(WorkflowStageStatus.pending) == "待命"
    assert agent_status_label(WorkflowStageStatus.running) == "执行中"
    assert agent_status_label(WorkflowStageStatus.waiting_human) == "等待人工"
    assert agent_status_label(WorkflowStageStatus.completed) == "已完成"
    assert agent_status_label(WorkflowStageStatus.failed) == "失败"


def test_agent_progress_for_status_keeps_terminal_and_waiting_values() -> None:
    assert agent_progress_for_status(WorkflowStageStatus.pending) == 0
    assert agent_progress_for_status(WorkflowStageStatus.running) == 62
    assert agent_progress_for_status(WorkflowStageStatus.waiting_human) == 48
    assert agent_progress_for_status(WorkflowStageStatus.completed) == 100
    assert agent_progress_for_status(WorkflowStageStatus.failed) == 100
