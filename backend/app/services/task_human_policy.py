from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status

from backend.app.api.errors import raise_store_http_error
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import (
    InteractionTriggerMode,
    TaskInteractionPolicyRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    normalize_workflow_stage,
)
from backend.app.services.task_human_access import resolve_human_request_assignee
from backend.app.services.task_human_context import get_task_human_loop
from backend.app.services.service_registry import (
    get_governance_store,
    get_task_store,
)
from backend.app.services.task_human_post_decision import save_task_waiting_for_human
from backend.app.services.task_human_policy_selection import (
    applicable_policies,
    is_stage_checkpoint_policy,
    policy_version_id,
)


def load_team_members_for_human(team_access: TeamAccessContext) -> list[TeamMemberRecord]:
    try:
        return get_governance_store().list_members(
            team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        raise_store_http_error(exc)

def validate_interaction_policy_assignees(
    policies: list[TaskInteractionPolicyRecord],
    team_access: TeamAccessContext,
) -> None:
    if not policies:
        return
    team_members = load_team_members_for_human(team_access)
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

def get_current_policy_cycle(task: TaskRecord) -> int:
    human_loop = get_task_human_loop(task)
    current_value = human_loop.get("current_run_cycle")
    if isinstance(current_value, int) and current_value > 0:
        return current_value
    policy_cycle = human_loop.get("policy_cycle")
    if isinstance(policy_cycle, int) and policy_cycle > 0:
        return policy_cycle
    return 1

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
        "checkpoint_mode": "sequential_stage_gate" if is_stage_checkpoint_policy(policy) else None,
    }

def apply_interaction_policies(
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
    for policy in applicable_policies(
        task.interaction_policies,
        existing_requests,
        trigger_mode=trigger_mode,
        checkpoint_only=checkpoint_only,
        skip_completed=skip_completed,
    ):
        normalized_stage = normalize_workflow_stage(policy.stage)
        version_id = policy_version_id(policy, cycle_id=cycle_id, trigger_mode=trigger_mode)
        if version_id in existing_version_ids:
            continue

        selection = stage_selection_map.get(normalized_stage.value)
        if team_members is None:
            team_members = load_team_members_for_human(team_access)
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
    paused_task = save_task_waiting_for_human(
        task_store,
        task,
        access_token=team_access.access_token,
        manual_hold=False,
    )
    return paused_task, created_count


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
