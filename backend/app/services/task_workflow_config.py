from __future__ import annotations

from backend.app.models.task import (
    TaskInteractionPolicyInput,
    TaskInteractionPolicyRecord,
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    TaskWorkflowConfigUpdateRequest,
    normalize_workflow_stage,
)


def apply_task_workflow_config(
    task: TaskRecord,
    payload: TaskWorkflowConfigUpdateRequest,
) -> TaskRecord:
    task.stage_routing = [
        _stage_routing_record(item)
        for item in payload.stage_routing
        if item.connector_id
    ]
    task.interaction_policies = [
        _interaction_policy_record(item, index=index)
        for index, item in enumerate(payload.interaction_policies)
    ]
    return task


def _stage_routing_record(item: TaskStageRoutingOverrideInput) -> TaskStageRoutingRecord:
    return TaskStageRoutingRecord(
        stage=normalize_workflow_stage(item.stage),
        connector_id=item.connector_id,
        model_name=item.model_name,
        selection_source="task_override",
    )


def _interaction_policy_record(
    item: TaskInteractionPolicyInput,
    *,
    index: int,
) -> TaskInteractionPolicyRecord:
    stage = normalize_workflow_stage(item.stage)
    return TaskInteractionPolicyRecord(
        policy_id=item.policy_id or f"{stage.value}:{index + 1}",
        enabled=item.enabled,
        stage=stage,
        trigger_mode=item.trigger_mode,
        assignee_type=item.assignee_type,
        assignee_value=item.assignee_value,
        request_type=item.request_type,
        title=item.title,
        summary=item.summary,
        suggested_action=item.suggested_action,
        timeout_minutes=item.timeout_minutes,
        artifact_paths=item.artifact_paths,
    )
