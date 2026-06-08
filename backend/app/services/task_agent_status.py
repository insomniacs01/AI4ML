from __future__ import annotations

from backend.app.models.task import WorkflowStageStatus


def agent_status_label(stage_status: WorkflowStageStatus) -> str:
    labels = {
        WorkflowStageStatus.pending: "待命",
        WorkflowStageStatus.running: "执行中",
        WorkflowStageStatus.waiting_human: "等待人工",
        WorkflowStageStatus.completed: "已完成",
        WorkflowStageStatus.failed: "失败",
    }
    return labels.get(stage_status, stage_status.value if hasattr(stage_status, "value") else str(stage_status))


def agent_progress_for_status(stage_status: WorkflowStageStatus) -> int:
    if stage_status == WorkflowStageStatus.completed:
        return 100
    if stage_status == WorkflowStageStatus.failed:
        return 100
    if stage_status == WorkflowStageStatus.running:
        return 62
    if stage_status == WorkflowStageStatus.waiting_human:
        return 48
    return 0
