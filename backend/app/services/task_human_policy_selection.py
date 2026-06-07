from __future__ import annotations

from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    HumanInteractionRequestStatus,
    InteractionTriggerMode,
    TaskHumanRequestRecord,
    TaskInteractionPolicyRecord,
    normalize_workflow_stage,
)
from backend.app.services.task_human_request_status import (
    ACTIVE_HUMAN_REQUEST_STATUSES,
    COMPLETED_HUMAN_REQUEST_STATUSES,
)


STAGE_CHECKPOINT_REQUEST_TYPE = "stage_checkpoint"
STAGE_CHECKPOINT_POLICY_PREFIX = "stage-checkpoint:"
STAGE_CHECKPOINT_ACTIVE_STATUSES = ACTIVE_HUMAN_REQUEST_STATUSES
STAGE_CHECKPOINT_COMPLETED_STATUSES = COMPLETED_HUMAN_REQUEST_STATUSES


def is_stage_checkpoint_policy(policy: TaskInteractionPolicyRecord) -> bool:
    return (
        policy.request_type == STAGE_CHECKPOINT_REQUEST_TYPE
        or policy.policy_id.startswith(STAGE_CHECKPOINT_POLICY_PREFIX)
    )


def applicable_policies(
    policies: list[TaskInteractionPolicyRecord],
    existing_requests: list[TaskHumanRequestRecord],
    *,
    trigger_mode: InteractionTriggerMode,
    checkpoint_only: bool,
    skip_completed: bool,
) -> list[TaskInteractionPolicyRecord]:
    next_checkpoint_policy = next_stage_checkpoint_policy(
        policies,
        existing_requests,
        trigger_mode=trigger_mode,
    )
    next_checkpoint_policy_id = getattr(next_checkpoint_policy, "policy_id", None)
    return [
        policy
        for policy in policies
        if should_apply_policy(
            policy,
            existing_requests,
            trigger_mode=trigger_mode,
            checkpoint_only=checkpoint_only,
            skip_completed=skip_completed,
            next_checkpoint_policy_id=next_checkpoint_policy_id,
        )
    ]


def policy_version_id(
    policy: TaskInteractionPolicyRecord,
    *,
    cycle_id: int,
    trigger_mode: InteractionTriggerMode,
) -> str:
    if is_stage_checkpoint_policy(policy):
        return f"{policy.policy_id}:stage-checkpoint"
    return f"{policy.policy_id}:{cycle_id}:{trigger_mode.value}"


def next_stage_checkpoint_policy(
    policies: list[TaskInteractionPolicyRecord],
    existing_requests: list[TaskHumanRequestRecord],
    *,
    trigger_mode: InteractionTriggerMode,
) -> TaskInteractionPolicyRecord | None:
    checkpoint_policies = [
        policy
        for policy in policies
        if policy.enabled
        and policy.trigger_mode == trigger_mode
        and is_stage_checkpoint_policy(policy)
    ]
    if not checkpoint_policies:
        return None

    stage_order = {stage.value: index for index, stage in enumerate(PRIMARY_WORKFLOW_STAGES)}
    checkpoint_policies.sort(
        key=lambda item: (
            stage_order.get(normalize_workflow_stage(item.stage).value, len(stage_order)),
            item.policy_id,
        )
    )
    status_by_policy = stage_checkpoint_status_by_policy(existing_requests)
    for policy in checkpoint_policies:
        status = status_by_policy.get(policy.policy_id)
        if status in STAGE_CHECKPOINT_ACTIVE_STATUSES:
            return None
        if status in STAGE_CHECKPOINT_COMPLETED_STATUSES:
            continue
        return policy
    return None


def should_apply_policy(
    policy: TaskInteractionPolicyRecord,
    existing_requests: list[TaskHumanRequestRecord],
    *,
    trigger_mode: InteractionTriggerMode,
    checkpoint_only: bool,
    skip_completed: bool,
    next_checkpoint_policy_id: str | None,
) -> bool:
    is_checkpoint = is_stage_checkpoint_policy(policy)
    if not policy.enabled or policy.trigger_mode != trigger_mode:
        return False
    if checkpoint_only and not is_checkpoint:
        return False
    if is_checkpoint and policy.policy_id != next_checkpoint_policy_id:
        return False
    if skip_completed and not is_checkpoint:
        return not policy_has_completed_request(existing_requests, policy, trigger_mode=trigger_mode)
    return True


def stage_checkpoint_status_by_policy(
    existing_requests: list[TaskHumanRequestRecord],
) -> dict[str, HumanInteractionRequestStatus]:
    status_by_policy: dict[str, HumanInteractionRequestStatus] = {}
    for request in existing_requests:
        payload = request.payload if isinstance(request.payload, dict) else {}
        policy_id = payload.get("policy_id")
        if not isinstance(policy_id, str) or not policy_id:
            continue
        if not _is_stage_checkpoint_request(payload, policy_id):
            continue
        current_status = request.status
        previous_status = status_by_policy.get(policy_id)
        if current_status in STAGE_CHECKPOINT_ACTIVE_STATUSES:
            status_by_policy[policy_id] = current_status
            continue
        if previous_status is None or previous_status not in STAGE_CHECKPOINT_ACTIVE_STATUSES:
            status_by_policy[policy_id] = current_status
    return status_by_policy


def policy_has_completed_request(
    existing_requests: list[TaskHumanRequestRecord],
    policy: TaskInteractionPolicyRecord,
    *,
    trigger_mode: InteractionTriggerMode,
) -> bool:
    for request in existing_requests:
        payload = request.payload if isinstance(request.payload, dict) else {}
        if payload.get("policy_id") != policy.policy_id:
            continue
        if payload.get("trigger_mode") != trigger_mode.value:
            continue
        if request.status in STAGE_CHECKPOINT_COMPLETED_STATUSES:
            return True
    return False


def _is_stage_checkpoint_request(payload: dict, policy_id: str) -> bool:
    return (
        payload.get("request_type") == STAGE_CHECKPOINT_REQUEST_TYPE
        or policy_id.startswith(STAGE_CHECKPOINT_POLICY_PREFIX)
    )
