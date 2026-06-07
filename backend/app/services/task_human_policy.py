from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status

from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    HumanInteractionRequestStatus,
    InteractionTriggerMode,
    TaskHumanRequestRecord,
    TaskInteractionPolicyRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    normalize_workflow_stage,
)
from backend.app.services.task_human_access import resolve_human_request_assignee
from backend.app.services.task_human_context import ensure_task_human_loop, get_task_human_loop
from backend.app.services.service_registry import (
    get_governance_store,
    get_task_human_collaboration_service,
    get_task_store,
)


from backend.app.services.task_routing import _raise_governance_http_error

STAGE_CHECKPOINT_REQUEST_TYPE = "stage_checkpoint"
STAGE_CHECKPOINT_POLICY_PREFIX = "stage-checkpoint:"
STAGE_CHECKPOINT_ACTIVE_STATUSES = {
    HumanInteractionRequestStatus.pending,
    HumanInteractionRequestStatus.open,
}
STAGE_CHECKPOINT_COMPLETED_STATUSES = {
    HumanInteractionRequestStatus.confirmed,
    HumanInteractionRequestStatus.modified,
    HumanInteractionRequestStatus.rejected,
    HumanInteractionRequestStatus.skipped,
    HumanInteractionRequestStatus.resolved,
}

def _load_team_members_for_human(team_access: TeamAccessContext) -> list[TeamMemberRecord]:
    try:
        return get_governance_store().list_members(
            team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)

def _validate_interaction_policy_assignees(
    policies: list[TaskInteractionPolicyRecord],
    team_access: TeamAccessContext,
) -> None:
    if not policies:
        return
    team_members = _load_team_members_for_human(team_access)
    for policy in policies:
        try:
            resolve_human_request_assignee(
                assignee_type=policy.assignee_type,
                assignee_value=policy.assignee_value,
                assigned_to=policy.assignee_value if policy.assignee_type.value == "member" else None,
                default_member_id=team_access.user.id,
                team_members=team_members,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

def _next_policy_cycle(task: TaskRecord) -> int:
    human_loop = ensure_task_human_loop(task)
    current_value = human_loop.get("policy_cycle")
    next_value = int(current_value) + 1 if isinstance(current_value, int) else 1
    human_loop["policy_cycle"] = next_value
    human_loop["current_run_cycle"] = next_value
    return next_value

def _get_current_policy_cycle(task: TaskRecord) -> int:
    human_loop = get_task_human_loop(task)
    current_value = human_loop.get("current_run_cycle")
    if isinstance(current_value, int) and current_value > 0:
        return current_value
    policy_cycle = human_loop.get("policy_cycle")
    if isinstance(policy_cycle, int) and policy_cycle > 0:
        return policy_cycle
    return 1

def _is_stage_checkpoint_policy(policy: TaskInteractionPolicyRecord) -> bool:
    return (
        policy.request_type == STAGE_CHECKPOINT_REQUEST_TYPE
        or policy.policy_id.startswith(STAGE_CHECKPOINT_POLICY_PREFIX)
    )

def _stage_checkpoint_status_by_policy(
    existing_requests: list[TaskHumanRequestRecord],
) -> dict[str, HumanInteractionRequestStatus]:
    status_by_policy: dict[str, HumanInteractionRequestStatus] = {}
    for request in existing_requests:
        payload = request.payload if isinstance(request.payload, dict) else {}
        policy_id = payload.get("policy_id")
        if not isinstance(policy_id, str) or not policy_id:
            continue
        if payload.get("request_type") != STAGE_CHECKPOINT_REQUEST_TYPE and not policy_id.startswith(STAGE_CHECKPOINT_POLICY_PREFIX):
            continue
        current_status = request.status
        previous_status = status_by_policy.get(policy_id)
        if current_status in STAGE_CHECKPOINT_ACTIVE_STATUSES:
            status_by_policy[policy_id] = current_status
            continue
        if previous_status is None or previous_status not in STAGE_CHECKPOINT_ACTIVE_STATUSES:
            status_by_policy[policy_id] = current_status
    return status_by_policy

def _policy_has_completed_request(
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

def _next_stage_checkpoint_policy(
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
        and _is_stage_checkpoint_policy(policy)
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
    status_by_policy = _stage_checkpoint_status_by_policy(existing_requests)
    for policy in checkpoint_policies:
        status = status_by_policy.get(policy.policy_id)
        if status in STAGE_CHECKPOINT_ACTIVE_STATUSES:
            return None
        if status in STAGE_CHECKPOINT_COMPLETED_STATUSES:
            continue
        return policy
    return None

def _build_policy_request_payload(
    policy: TaskInteractionPolicyRecord,
    *,
    selection: TaskStageRoutingRecord | None,
) -> dict:
    return {
        "request_type": policy.request_type,
        "title": policy.title,
        "summary": policy.summary,
        "suggested_action": policy.suggested_action,
        "artifact_paths": policy.artifact_paths,
        "trigger_mode": policy.trigger_mode.value,
        "policy_id": policy.policy_id,
        "selected_connector_id": selection.connector_id if selection else None,
        "selected_model_name": selection.model_name if selection else None,
        "checkpoint_mode": "sequential_stage_gate" if _is_stage_checkpoint_policy(policy) else None,
    }

def _apply_interaction_policies(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    trigger_mode: InteractionTriggerMode,
    cycle_id: int,
    stage_selection_map: dict[str, TaskStageRoutingRecord],
    checkpoint_only: bool = False,
    skip_completed: bool = False,
) -> tuple[TaskRecord, int]:
    task_store = get_task_store()
    existing_requests = task_store.list_human_requests(task.team_id, task.id, access_token=team_access.access_token)
    existing_version_ids = {item.version_id for item in existing_requests if item.version_id}
    team_members: list[TeamMemberRecord] | None = None

    created_count = 0
    for policy in _applicable_policies(
        task.interaction_policies,
        existing_requests,
        trigger_mode=trigger_mode,
        checkpoint_only=checkpoint_only,
        skip_completed=skip_completed,
    ):
        normalized_stage = normalize_workflow_stage(policy.stage)
        version_id = _policy_version_id(policy, cycle_id=cycle_id, trigger_mode=trigger_mode)
        if version_id in existing_version_ids:
            continue

        selection = stage_selection_map.get(normalized_stage.value)
        if team_members is None:
            team_members = _load_team_members_for_human(team_access)
        assignee_type, assignee_value, assigned_to = _resolve_policy_assignee(
            policy,
            team_access,
            team_members,
        )
        _create_policy_human_request(
            task_store,
            task,
            team_access,
            policy,
            normalized_stage,
            selection,
            version_id,
            assignee_type=assignee_type.value,
            assignee_value=assignee_value,
            assigned_to=assigned_to,
        )
        created_count += 1
        existing_version_ids.add(version_id)

    if created_count == 0:
        return task, 0

    task.notes = (
        f"已根据任务的人机协同策略自动创建 {created_count} 个待处理节点，"
        f"当前阶段为 {trigger_mode.value}。"
    )
    collaboration_service = get_task_human_collaboration_service()
    paused_task = collaboration_service._mark_task_waiting(  # noqa: SLF001
        task,
        access_token=team_access.access_token,
        manual_hold=False,
    )
    return paused_task, created_count


def _applicable_policies(
    policies: list[TaskInteractionPolicyRecord],
    existing_requests: list[TaskHumanRequestRecord],
    *,
    trigger_mode: InteractionTriggerMode,
    checkpoint_only: bool,
    skip_completed: bool,
) -> list[TaskInteractionPolicyRecord]:
    next_checkpoint_policy = _next_stage_checkpoint_policy(
        policies,
        existing_requests,
        trigger_mode=trigger_mode,
    )
    next_checkpoint_policy_id = getattr(next_checkpoint_policy, "policy_id", None)
    return [
        policy
        for policy in policies
        if _should_apply_policy(
            policy,
            existing_requests,
            trigger_mode=trigger_mode,
            checkpoint_only=checkpoint_only,
            skip_completed=skip_completed,
            next_checkpoint_policy_id=next_checkpoint_policy_id,
        )
    ]


def _should_apply_policy(
    policy: TaskInteractionPolicyRecord,
    existing_requests: list[TaskHumanRequestRecord],
    *,
    trigger_mode: InteractionTriggerMode,
    checkpoint_only: bool,
    skip_completed: bool,
    next_checkpoint_policy_id: str | None,
) -> bool:
    is_checkpoint = _is_stage_checkpoint_policy(policy)
    if not policy.enabled or policy.trigger_mode != trigger_mode:
        return False
    if checkpoint_only and not is_checkpoint:
        return False
    if is_checkpoint and policy.policy_id != next_checkpoint_policy_id:
        return False
    if skip_completed and not is_checkpoint:
        return not _policy_has_completed_request(existing_requests, policy, trigger_mode=trigger_mode)
    return True


def _policy_version_id(
    policy: TaskInteractionPolicyRecord,
    *,
    cycle_id: int,
    trigger_mode: InteractionTriggerMode,
) -> str:
    if _is_stage_checkpoint_policy(policy):
        return f"{policy.policy_id}:stage-checkpoint"
    return f"{policy.policy_id}:{cycle_id}:{trigger_mode.value}"


def _resolve_policy_assignee(
    policy: TaskInteractionPolicyRecord,
    team_access: TeamAccessContext,
    team_members: list[TeamMemberRecord],
):
    try:
        return resolve_human_request_assignee(
            assignee_type=policy.assignee_type,
            assignee_value=policy.assignee_value,
            assigned_to=policy.assignee_value if policy.assignee_type.value == "member" else None,
            default_member_id=team_access.user.id,
            team_members=team_members,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def _create_policy_human_request(
    task_store,
    task: TaskRecord,
    team_access: TeamAccessContext,
    policy: TaskInteractionPolicyRecord,
    normalized_stage,
    selection: TaskStageRoutingRecord | None,
    version_id: str,
    *,
    assignee_type: str,
    assignee_value: str,
    assigned_to: str | None,
) -> None:
    timeout_at = None
    if policy.timeout_minutes is not None:
        timeout_at = task.updated_at + timedelta(minutes=policy.timeout_minutes)
    task_store.create_human_request(
        team_id=task.team_id,
        task_id=task.id,
        stage=normalized_stage,
        requested_by=team_access.user.id,
        assigned_to=assigned_to,
        assignee_type=assignee_type,
        assignee_value=assignee_value,
        timeout_at=timeout_at,
        version_id=version_id,
        payload=_build_policy_request_payload(policy, selection=selection),
        access_token=team_access.access_token,
    )
