from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import TaskHumanRequestDecisionRequest, TaskHumanRequestRecord, TaskRecord
from backend.app.services.task_human_parameters import apply_human_decision_parameters
from backend.app.services.task_human_payloads import build_human_decision_payload, is_rerun_decision_action
from backend.app.services.task_human_stages import stage_key
from backend.app.services.task_human_transitions import status_for_human_decision_action


@dataclass(frozen=True)
class AppliedHumanDecision:
    request: TaskHumanRequestRecord
    rerun_from_stage: str | None


def apply_human_decision(
    task_store: Any,
    task: TaskRecord,
    request: TaskHumanRequestRecord,
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
    actor_role: str,
    access_token: str,
    decided_at: datetime | None = None,
) -> AppliedHumanDecision:
    request.status = status_for_human_decision_action(payload.action)
    requires_rerun = is_rerun_decision_action(payload.action)
    rerun_from_stage = stage_key(request.stage) if requires_rerun else None
    request.decision = build_human_decision_payload(
        payload,
        decided_by=decided_by,
        actor_role=actor_role,
        decided_at=decided_at or datetime.now(timezone.utc),
        requires_rerun=requires_rerun,
        rerun_from_stage=rerun_from_stage,
    )
    apply_human_decision_parameters(task, request, payload, decided_by=decided_by)
    task_store.update_human_request(request, access_token=access_token)
    return AppliedHumanDecision(request=request, rerun_from_stage=rerun_from_stage)
