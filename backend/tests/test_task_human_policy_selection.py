from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    InteractionAssigneeType,
    InteractionTriggerMode,
    TaskHumanRequestRecord,
    TaskInteractionPolicyRecord,
    WorkflowStage,
)
from backend.app.services.task_human_policy_selection import (
    STAGE_CHECKPOINT_REQUEST_TYPE,
    applicable_policies,
    next_stage_checkpoint_policy,
    policy_version_id,
    stage_checkpoint_status_by_policy,
)


def _policy(
    policy_id: str,
    *,
    stage: WorkflowStage,
    request_type: str = "model_review",
    trigger_mode: InteractionTriggerMode = InteractionTriggerMode.before_run,
    enabled: bool = True,
) -> TaskInteractionPolicyRecord:
    return TaskInteractionPolicyRecord(
        policy_id=policy_id,
        enabled=enabled,
        stage=stage,
        trigger_mode=trigger_mode,
        assignee_type=InteractionAssigneeType.member,
        assignee_value="user-1",
        request_type=request_type,
        title=f"Confirm {stage.value}",
        summary=f"Confirm {stage.value}.",
    )


def _checkpoint_policy(policy_id: str, *, stage: WorkflowStage) -> TaskInteractionPolicyRecord:
    return _policy(policy_id, stage=stage, request_type=STAGE_CHECKPOINT_REQUEST_TYPE)


def _request(
    policy_id: str,
    *,
    status: HumanInteractionRequestStatus,
    request_type: str = "model_review",
    trigger_mode: InteractionTriggerMode = InteractionTriggerMode.before_run,
) -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id=f"request-{policy_id}",
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.model_selection,
        status=status,
        requested_by="user-1",
        assigned_to="user-1",
        assignee_type=InteractionAssigneeType.member,
        assignee_value="user-1",
        payload={
            "policy_id": policy_id,
            "request_type": request_type,
            "trigger_mode": trigger_mode.value,
        },
        created_at=now,
        updated_at=now,
    )


def test_next_stage_checkpoint_policy_respects_stage_order_and_completed_requests() -> None:
    requirement_policy = _checkpoint_policy(
        "stage-checkpoint:requirement_analysis",
        stage=WorkflowStage.requirement_analysis,
    )
    data_policy = _checkpoint_policy("stage-checkpoint:data_analysis", stage=WorkflowStage.data_analysis)

    assert next_stage_checkpoint_policy(
        [data_policy, requirement_policy],
        [],
        trigger_mode=InteractionTriggerMode.before_run,
    ) == requirement_policy

    assert next_stage_checkpoint_policy(
        [data_policy, requirement_policy],
        [
            _request(
                requirement_policy.policy_id,
                status=HumanInteractionRequestStatus.confirmed,
                request_type=STAGE_CHECKPOINT_REQUEST_TYPE,
            )
        ],
        trigger_mode=InteractionTriggerMode.before_run,
    ) == data_policy


def test_active_stage_checkpoint_request_blocks_next_checkpoint_creation() -> None:
    requirement_policy = _checkpoint_policy(
        "stage-checkpoint:requirement_analysis",
        stage=WorkflowStage.requirement_analysis,
    )
    data_policy = _checkpoint_policy("stage-checkpoint:data_analysis", stage=WorkflowStage.data_analysis)

    assert next_stage_checkpoint_policy(
        [requirement_policy, data_policy],
        [
            _request(
                requirement_policy.policy_id,
                status=HumanInteractionRequestStatus.open,
                request_type=STAGE_CHECKPOINT_REQUEST_TYPE,
            )
        ],
        trigger_mode=InteractionTriggerMode.before_run,
    ) is None


def test_applicable_policies_keeps_next_checkpoint_and_skips_completed_non_checkpoint() -> None:
    checkpoint_policy = _checkpoint_policy(
        "stage-checkpoint:requirement_analysis",
        stage=WorkflowStage.requirement_analysis,
    )
    model_policy = _policy("model-review", stage=WorkflowStage.model_selection)

    selected = applicable_policies(
        [checkpoint_policy, model_policy],
        [_request("model-review", status=HumanInteractionRequestStatus.confirmed)],
        trigger_mode=InteractionTriggerMode.before_run,
        checkpoint_only=False,
        skip_completed=True,
    )

    assert selected == [checkpoint_policy]


def test_policy_version_id_uses_stable_checkpoint_version() -> None:
    checkpoint_policy = _checkpoint_policy(
        "stage-checkpoint:requirement_analysis",
        stage=WorkflowStage.requirement_analysis,
    )
    model_policy = _policy("model-review", stage=WorkflowStage.model_selection)

    assert (
        policy_version_id(checkpoint_policy, cycle_id=3, trigger_mode=InteractionTriggerMode.before_run)
        == "stage-checkpoint:requirement_analysis:stage-checkpoint"
    )
    assert (
        policy_version_id(model_policy, cycle_id=3, trigger_mode=InteractionTriggerMode.before_run)
        == "model-review:3:before_run"
    )


def test_stage_checkpoint_status_keeps_active_status_over_completed_status() -> None:
    policy_id = "stage-checkpoint:requirement_analysis"

    statuses = stage_checkpoint_status_by_policy(
        [
            _request(policy_id, status=HumanInteractionRequestStatus.open, request_type=STAGE_CHECKPOINT_REQUEST_TYPE),
            _request(
                policy_id,
                status=HumanInteractionRequestStatus.confirmed,
                request_type=STAGE_CHECKPOINT_REQUEST_TYPE,
            ),
        ]
    )

    assert statuses[policy_id] == HumanInteractionRequestStatus.open
