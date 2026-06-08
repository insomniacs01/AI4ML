from __future__ import annotations

from backend.app.models.task import WorkflowStageStatus


AGENT_STATUS_LABELS = {
    WorkflowStageStatus.pending: "待命",
    WorkflowStageStatus.running: "执行中",
    WorkflowStageStatus.waiting_human: "等待人工",
    WorkflowStageStatus.completed: "已完成",
    WorkflowStageStatus.failed: "失败",
}

AGENT_STATUS_PROGRESS = {
    WorkflowStageStatus.pending: 0,
    WorkflowStageStatus.running: 62,
    WorkflowStageStatus.waiting_human: 48,
    WorkflowStageStatus.completed: 100,
    WorkflowStageStatus.failed: 100,
}


def agent_status_label(stage_status: object) -> str:
    return AGENT_STATUS_LABELS.get(stage_status, _status_value(stage_status))


def agent_progress_for_status(stage_status: object) -> int:
    return AGENT_STATUS_PROGRESS.get(stage_status, 0)


def _status_value(stage_status: object) -> str:
    return str(stage_status.value if hasattr(stage_status, "value") else stage_status)
