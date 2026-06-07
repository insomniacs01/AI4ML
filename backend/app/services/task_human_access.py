from __future__ import annotations

from typing import NamedTuple

from backend.app.core.supabase_auth import TEAM_ADMIN_ROLES
from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import InteractionAssigneeType, TaskHumanRequestRecord


class ResolvedHumanAssignee(NamedTuple):
    assignee_type: InteractionAssigneeType
    assignee_value: str
    assigned_to: str | None


def parse_candidate_pool(value: str | None) -> list[str]:
    return [
        item.strip()
        for item in str(value or "").replace(";", ",").split(",")
        if item.strip()
    ]


def resolve_human_request_assignee(
    *,
    assignee_type: InteractionAssigneeType | str | None,
    assignee_value: str | None,
    assigned_to: str | None,
    default_member_id: str,
    team_members: list[TeamMemberRecord],
) -> ResolvedHumanAssignee:
    resolved_type = assignee_type or InteractionAssigneeType.member
    if not isinstance(resolved_type, InteractionAssigneeType):
        resolved_type = InteractionAssigneeType(str(resolved_type))

    resolved_value = (assignee_value or assigned_to or default_member_id or "").strip()
    if not resolved_value:
        raise RuntimeError("human request assignee is required")

    active_members = [item for item in team_members if item.member_status == "active"]
    active_member_ids = {item.user_id for item in active_members}
    active_roles = {str(item.role) for item in active_members}

    if resolved_type == InteractionAssigneeType.member:
        if resolved_value not in active_member_ids:
            raise RuntimeError("human request assignee member is not an active member of this team")
        return ResolvedHumanAssignee(resolved_type, resolved_value, resolved_value)

    if resolved_type == InteractionAssigneeType.role:
        if resolved_value not in active_roles:
            raise RuntimeError("human request assignee role has no active member in this team")
        return ResolvedHumanAssignee(resolved_type, resolved_value, None)

    if resolved_type == InteractionAssigneeType.candidate_pool:
        if not parse_candidate_pool(resolved_value):
            raise RuntimeError("human request candidate pool is empty")
        return ResolvedHumanAssignee(resolved_type, resolved_value, None)

    raise RuntimeError(f"unsupported human request assignee type: {resolved_type}")


def can_actor_view_human_request(
    request: TaskHumanRequestRecord,
    *,
    actor_id: str,
    actor_role: str,
) -> bool:
    if actor_id == request.requested_by:
        return True
    if request.assignee_type == InteractionAssigneeType.member:
        return actor_id in {request.assigned_to, request.assignee_value}
    if request.assignee_type == InteractionAssigneeType.role:
        return actor_role == request.assignee_value
    if request.assignee_type == InteractionAssigneeType.candidate_pool:
        candidates = set(parse_candidate_pool(request.assignee_value))
        return actor_id in candidates or actor_role in candidates
    return False


def human_request_decision_denial_reason(
    request: TaskHumanRequestRecord,
    *,
    actor_id: str,
    actor_role: str,
) -> str | None:
    if actor_role in TEAM_ADMIN_ROLES:
        return None
    if request.assignee_type == InteractionAssigneeType.member:
        if actor_id in {request.assigned_to, request.assignee_value}:
            return None
        return "Only the assigned member or a team admin can decide this human request."
    if request.assignee_type == InteractionAssigneeType.role:
        if actor_role == request.assignee_value:
            return None
        return "Only members with the assigned role or a team admin can decide this human request."
    if request.assignee_type == InteractionAssigneeType.candidate_pool:
        candidates = set(parse_candidate_pool(request.assignee_value))
        if actor_id in candidates or actor_role in candidates:
            return None
        return "Only a candidate-pool member or a team admin can decide this human request."
    if actor_id == request.requested_by:
        return None
    return "Only the request owner, assignee, or a team admin can decide this human request."


def assert_actor_can_decide_human_request(
    request: TaskHumanRequestRecord,
    *,
    actor_id: str,
    actor_role: str,
) -> None:
    denial_reason = human_request_decision_denial_reason(request, actor_id=actor_id, actor_role=actor_role)
    if denial_reason is not None:
        raise PermissionError(denial_reason)
