from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    normalize_workflow_stage,
)
from backend.app.services.task_human_access import ResolvedHumanAssignee
from backend.app.services.task_human_payloads import (
    build_reassigned_decision_payload,
    build_reassigned_request_payload,
    resolve_reassign_timeout,
)


def reassign_human_request(
    task_store: Any,
    task: TaskRecord,
    request: TaskHumanRequestRecord,
    payload: TaskHumanRequestDecisionRequest,
    *,
    assignee: ResolvedHumanAssignee,
    decided_by: str,
    actor_role: str,
    access_token: str,
    decided_at: datetime | None = None,
) -> TaskHumanRequestRecord:
    now = decided_at or datetime.now(timezone.utc)
    request.status = HumanInteractionRequestStatus.reassigned
    request.decision = build_reassigned_decision_payload(
        payload,
        decided_by=decided_by,
        actor_role=actor_role,
        decided_at=now,
        assignee_type=assignee.assignee_type,
        assignee_value=assignee.assignee_value,
        assigned_to=assignee.assigned_to,
    )
    updated_request = task_store.update_human_request(request, access_token=access_token)

    timeout_at = resolve_reassign_timeout(
        request,
        reassign_timeout_minutes=payload.reassign_timeout_minutes,
        now=now,
    )
    reassigned_payload = build_reassigned_request_payload(
        request,
        payload,
        decided_by=decided_by,
        actor_role=actor_role,
    )
    version_seed = request.version_id or request.id
    task_store.create_human_request(
        team_id=task.team_id,
        task_id=task.id,
        stage=normalize_workflow_stage(request.stage),
        requested_by=decided_by,
        assigned_to=assignee.assigned_to,
        assignee_type=assignee.assignee_type.value,
        assignee_value=assignee.assignee_value,
        timeout_at=timeout_at,
        version_id=f"{version_seed}:reassigned:{int(now.timestamp())}",
        payload=reassigned_payload,
        access_token=access_token,
    )
    return updated_request
