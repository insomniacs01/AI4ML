from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_agent_definitions import agent_runtime_spec_for_stage
from backend.app.services.task_agent_status import agent_progress_for_status
from backend.app.services.task_human_request_status import human_request_is_active


@dataclass(frozen=True)
class MissingAgentRuntime:
    agent_id: str
    stage: WorkflowStage
    name: str
    role: str
    short_role: str
    status: WorkflowStageStatus
    progress: int
    current_task: str
    selected_connector_id: str | None
    model_name: str | None
    selection_source: str | None
    artifact_refs: Any | None
    log_excerpt: str | None
    worker_id: str


def build_missing_agent_runtimes(
    *,
    task_id: str,
    stages: list[WorkflowStageRecord],
    human_requests: list[TaskHumanRequestRecord],
    agent_runs: list[TaskAgentRuntimeRecord],
) -> list[MissingAgentRuntime]:
    existing_agent_ids = {record.agent_id for record in agent_runs}
    stages_by_key = {normalize_workflow_stage(record.stage).value: record for record in stages}
    waiting_stage_keys = {
        normalize_workflow_stage(request.stage).value
        for request in human_requests
        if human_request_is_active(request)
    }

    missing_runtimes: list[MissingAgentRuntime] = []
    for stage in PRIMARY_WORKFLOW_STAGES:
        stage_key = stage.value
        if stage_key in existing_agent_ids:
            continue
        stage_record = stages_by_key.get(stage_key)
        agent_spec = agent_runtime_spec_for_stage(stage)
        status = _runtime_status(stage_record, stage_key=stage_key, waiting_stage_keys=waiting_stage_keys)
        missing_runtimes.append(
            MissingAgentRuntime(
                agent_id=stage_key,
                stage=stage,
                name=str(agent_spec["name"]),
                role=str(agent_spec["role"]),
                short_role=str(agent_spec["short_role"]),
                status=status,
                progress=agent_progress_for_status(status),
                current_task=_runtime_current_task(stage_record, default_description=str(agent_spec["description"])),
                selected_connector_id=stage_record.selected_connector_id if stage_record else None,
                model_name=stage_record.model_name if stage_record else None,
                selection_source=stage_record.selection_source if stage_record else None,
                artifact_refs=stage_record.artifact_refs if stage_record else None,
                log_excerpt=stage_record.log_excerpt if stage_record else None,
                worker_id=f"backend-agent-worker:{task_id}:{stage_key}",
            )
        )
    return missing_runtimes


def _runtime_status(
    stage_record: WorkflowStageRecord | None,
    *,
    stage_key: str,
    waiting_stage_keys: set[str],
) -> WorkflowStageStatus:
    if stage_key in waiting_stage_keys:
        return WorkflowStageStatus.waiting_human
    if stage_record is not None:
        return stage_record.status
    return WorkflowStageStatus.pending


def _runtime_current_task(stage_record: WorkflowStageRecord | None, *, default_description: str) -> str:
    if stage_record is not None and stage_record.summary:
        return stage_record.summary
    return default_description
