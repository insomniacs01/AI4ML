from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.app.models.task import (
    HumanInteractionDecisionAction,
    InteractionAssigneeType,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
)
from backend.app.services.task_human_stages import stage_key


RERUN_DECISION_ACTIONS = {
    HumanInteractionDecisionAction.revise,
    HumanInteractionDecisionAction.reject,
}


def is_rerun_decision_action(action: HumanInteractionDecisionAction) -> bool:
    return action in RERUN_DECISION_ACTIONS


def build_human_request_payload(payload: TaskHumanRequestCreateRequest, *, actor_role: str) -> dict[str, Any]:
    return {
        "request_type": payload.request_type,
        "title": payload.title,
        "summary": payload.summary,
        "suggested_action": payload.suggested_action,
        "artifact_paths": payload.artifact_paths,
        "details": payload.details,
        "created_by_role": actor_role,
    }


def build_human_decision_payload(
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
    actor_role: str,
    decided_at: datetime,
    requires_rerun: bool,
    rerun_from_stage: str | None,
) -> dict[str, Any]:
    return {
        "action": payload.action.value,
        "summary": payload.decision_summary,
        "artifact_paths": payload.artifact_paths,
        "details": payload.details,
        "decided_by": decided_by,
        "decided_by_role": actor_role,
        "decided_at": decided_at.isoformat(),
        "requires_rerun": requires_rerun,
        "rerun_from_stage": rerun_from_stage,
    }


def build_reassigned_decision_payload(
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
    actor_role: str,
    decided_at: datetime,
    assignee_type: InteractionAssigneeType,
    assignee_value: str,
    assigned_to: str | None,
) -> dict[str, Any]:
    return {
        "action": payload.action.value,
        "summary": payload.decision_summary,
        "artifact_paths": payload.artifact_paths,
        "details": payload.details,
        "decided_by": decided_by,
        "decided_by_role": actor_role,
        "decided_at": decided_at.isoformat(),
        "reassigned_to": {
            "assignee_type": assignee_type.value,
            "assignee_value": assignee_value,
            "assigned_to": assigned_to,
        },
    }


def build_reassigned_request_payload(
    request: TaskHumanRequestRecord,
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
    actor_role: str,
) -> dict[str, Any]:
    request_payload = read_human_request_payload(request)
    return {
        **request_payload,
        "reassigned_from_request_id": request.id,
        "reassigned_by": decided_by,
        "reassigned_by_role": actor_role,
        "reassign_reason": payload.decision_summary,
        "previous_assignee_type": request.assignee_type.value if request.assignee_type else None,
        "previous_assignee_value": request.assignee_value,
    }


def resolve_reassign_timeout(
    request: TaskHumanRequestRecord,
    *,
    reassign_timeout_minutes: int | None,
    now: datetime,
) -> datetime | None:
    if reassign_timeout_minutes is not None:
        return now + timedelta(minutes=reassign_timeout_minutes)
    if request.timeout_at and request.timeout_at > now:
        return request.timeout_at
    return None


def read_human_request_payload(request: TaskHumanRequestRecord) -> dict[str, Any]:
    return request.payload if isinstance(request.payload, dict) else {}


def resolve_decision_artifact_paths(
    payload: TaskHumanRequestDecisionRequest,
    *,
    request_payload: dict[str, Any],
) -> list[str]:
    if payload.artifact_paths:
        return payload.artifact_paths
    request_artifact_paths = request_payload.get("artifact_paths")
    if not isinstance(request_artifact_paths, list):
        return []
    return [str(item).strip() for item in request_artifact_paths if str(item).strip()]


def build_human_decision_history_entry(
    request: TaskHumanRequestRecord,
    payload: TaskHumanRequestDecisionRequest,
    *,
    updated_at: datetime,
) -> dict[str, Any]:
    request_payload = read_human_request_payload(request)
    decision_payload = request.decision if isinstance(request.decision, dict) else {}
    return {
        "request_id": request.id,
        "stage": stage_key(request.stage),
        "action": payload.action.value,
        "title": request_payload.get("title"),
        "request_type": request_payload.get("request_type"),
        "request_summary": request_payload.get("summary"),
        "suggested_action": request_payload.get("suggested_action"),
        "decision_summary": payload.decision_summary,
        "artifact_paths": resolve_decision_artifact_paths(payload, request_payload=request_payload),
        "decision_details": payload.details,
        "resume_task": payload.resume_task,
        "requires_rerun": is_rerun_decision_action(payload.action),
        "reassign_assignee_type": payload.reassign_assignee_type.value if payload.reassign_assignee_type else None,
        "reassign_assignee_value": payload.reassign_assignee_value,
        "reassign_assigned_to": payload.reassign_assigned_to,
        "decided_by": decision_payload.get("decided_by"),
        "decided_at": decision_payload.get("decided_at") or updated_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }
