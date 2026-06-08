from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import (
    InteractionAssigneeType,
    TaskHumanRequestCreateRequest,
    WorkflowStage,
    normalize_workflow_stage,
)
from backend.app.services.task_human_access import resolve_human_request_assignee
from backend.app.services.task_human_payloads import build_human_request_payload


@dataclass(frozen=True)
class HumanRequestCreation:
    stage: WorkflowStage
    assigned_to: str | None
    assignee_type: InteractionAssigneeType
    assignee_value: str
    timeout_at: datetime | None
    payload: dict[str, Any]


def build_human_request_creation(
    payload: TaskHumanRequestCreateRequest,
    *,
    requested_by: str,
    actor_role: str,
    team_members: list[TeamMemberRecord],
    now: datetime | None = None,
) -> HumanRequestCreation:
    assignee_type, assignee_value, assigned_to = resolve_human_request_assignee(
        assignee_type=payload.assignee_type,
        assignee_value=payload.assignee_value,
        assigned_to=payload.assigned_to,
        default_member_id=requested_by,
        team_members=team_members,
    )
    return HumanRequestCreation(
        stage=normalize_workflow_stage(payload.stage),
        assigned_to=assigned_to,
        assignee_type=assignee_type,
        assignee_value=assignee_value,
        timeout_at=_creation_timeout(payload.timeout_minutes, now=now),
        payload=build_human_request_payload(payload, actor_role=actor_role),
    )


def _creation_timeout(timeout_minutes: int | None, *, now: datetime | None) -> datetime | None:
    if timeout_minutes is None:
        return None
    return (now or datetime.now(timezone.utc)) + timedelta(minutes=timeout_minutes)
