from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    InteractionAssigneeType,
    InteractionTriggerMode,
    TaskInteractionPolicyInput,
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStatus,
    TaskWorkflowConfigUpdateRequest,
    WorkflowStage,
)
from backend.app.services.task_workflow_config import apply_task_workflow_config


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-workflow-config",
        team_id="team-1",
        created_by="user-1",
        name="Workflow Config",
        description="Workflow config task.",
        status=TaskStatus.uploaded,
        created_at=now,
        updated_at=now,
    )


def _policy(
    stage: WorkflowStage,
    *,
    policy_id: str | None = None,
    title: str = "Review",
) -> TaskInteractionPolicyInput:
    return TaskInteractionPolicyInput(
        policy_id=policy_id,
        enabled=True,
        stage=stage,
        trigger_mode=InteractionTriggerMode.before_run,
        assignee_type=InteractionAssigneeType.member,
        assignee_value="user-1",
        request_type="stage_checkpoint",
        title=title,
        summary=f"{title} summary.",
        suggested_action="Confirm.",
        timeout_minutes=30,
        artifact_paths=["artifact.txt"],
    )


def test_apply_task_workflow_config_keeps_only_connector_backed_stage_overrides() -> None:
    payload = TaskWorkflowConfigUpdateRequest(
        stage_routing=[
            TaskStageRoutingOverrideInput(
                stage=WorkflowStage.data_analysis,
                connector_id="connector-1",
                model_name="model-a",
            ),
            TaskStageRoutingOverrideInput(
                stage=WorkflowStage.model_selection,
                connector_id=None,
                model_name=None,
            ),
        ],
        interaction_policies=[],
    )

    updated = apply_task_workflow_config(_task(), payload)

    assert len(updated.stage_routing) == 1
    assert updated.stage_routing[0].stage == WorkflowStage.data_analysis
    assert updated.stage_routing[0].connector_id == "connector-1"
    assert updated.stage_routing[0].model_name == "model-a"
    assert updated.stage_routing[0].selection_source == "task_override"


def test_apply_task_workflow_config_builds_policy_records() -> None:
    payload = TaskWorkflowConfigUpdateRequest(
        stage_routing=[],
        interaction_policies=[
            _policy(WorkflowStage.data_analysis),
            _policy(WorkflowStage.training_validation, policy_id="custom-policy", title="Validate"),
        ],
    )

    updated = apply_task_workflow_config(_task(), payload)

    assert [policy.policy_id for policy in updated.interaction_policies] == [
        "data_analysis:1",
        "custom-policy",
    ]
    first_policy = updated.interaction_policies[0]
    assert first_policy.stage == WorkflowStage.data_analysis
    assert first_policy.trigger_mode == InteractionTriggerMode.before_run
    assert first_policy.assignee_type == InteractionAssigneeType.member
    assert first_policy.assignee_value == "user-1"
    assert first_policy.request_type == "stage_checkpoint"
    assert first_policy.artifact_paths == ["artifact.txt"]
