from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.task import (
    TaskRecord,
    TaskStageRoutingRecord,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_agent_definitions import agent_runtime_spec_for_stage
from backend.app.services.task_agent_status import agent_progress_for_status, agent_status_label


@dataclass(frozen=True)
class WorkflowStageTrackingContext:
    stage: WorkflowStage
    stage_status: WorkflowStageStatus
    status_value: str
    current_task: str
    agent_id: str
    agent_name: str
    agent_role: str
    agent_short_role: str
    progress: int
    selected_connector_id: str | None
    model_name: str | None
    selection_source: str | None
    worker_id: str
    event_text: str


def build_workflow_stage_tracking_context(
    task: TaskRecord,
    *,
    stage: WorkflowStage,
    stage_status: WorkflowStageStatus,
    summary: str,
    stage_record: TaskStageRoutingRecord | None,
) -> WorkflowStageTrackingContext:
    agent_spec = agent_runtime_spec_for_stage(stage)
    agent_name = str(agent_spec["name"])
    agent_role = str(agent_spec["role"])
    current_task = summary
    status_value = stage_status.value if hasattr(stage_status, "value") else str(stage_status)
    worker_id = f"backend-agent-worker:{task.id}:{normalize_workflow_stage(stage).value}"
    return WorkflowStageTrackingContext(
        stage=stage,
        stage_status=stage_status,
        status_value=status_value,
        current_task=current_task,
        agent_id=str(agent_spec["agent_id"]),
        agent_name=agent_name,
        agent_role=agent_role,
        agent_short_role=str(agent_spec["short_role"]),
        progress=agent_progress_for_status(stage_status),
        selected_connector_id=stage_record.connector_id if stage_record else None,
        model_name=stage_record.model_name if stage_record else None,
        selection_source=stage_record.selection_source if stage_record else None,
        worker_id=worker_id,
        event_text=f"{agent_name}（{agent_role}）{agent_status_label(stage_status)}：{current_task}",
    )
