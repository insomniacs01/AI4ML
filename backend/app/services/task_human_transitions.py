from __future__ import annotations

from datetime import datetime
from enum import Enum

from backend.app.models.task import HumanInteractionDecisionAction, HumanInteractionRequestStatus
from backend.app.services.task_human_payloads import is_rerun_decision_action


class PostDecisionTaskAction(str, Enum):
    wait_for_human = "wait_for_human"
    ready_for_rerun = "ready_for_rerun"
    request_rerun_and_wait = "request_rerun_and_wait"
    resume_task = "resume_task"


WAIT_FOR_HUMAN_ACTION = PostDecisionTaskAction.wait_for_human
READY_FOR_RERUN_ACTION = PostDecisionTaskAction.ready_for_rerun
REQUEST_RERUN_AND_WAIT_ACTION = PostDecisionTaskAction.request_rerun_and_wait
RESUME_TASK_ACTION = PostDecisionTaskAction.resume_task
EXPIRED_HUMAN_DECISION_SUMMARY = "Request expired before a human decision was submitted."


def resolve_human_decision_task_action(
    action: HumanInteractionDecisionAction,
    *,
    open_request_count: int,
    resume_task: bool,
) -> PostDecisionTaskAction:
    if open_request_count > 0:
        return WAIT_FOR_HUMAN_ACTION
    if action == HumanInteractionDecisionAction.block:
        return WAIT_FOR_HUMAN_ACTION
    if is_rerun_decision_action(action) and resume_task:
        return READY_FOR_RERUN_ACTION
    if is_rerun_decision_action(action):
        return REQUEST_RERUN_AND_WAIT_ACTION
    if resume_task:
        return RESUME_TASK_ACTION
    return WAIT_FOR_HUMAN_ACTION


def status_for_human_decision_action(action: HumanInteractionDecisionAction) -> HumanInteractionRequestStatus:
    if action == HumanInteractionDecisionAction.approve:
        return HumanInteractionRequestStatus.confirmed
    if action == HumanInteractionDecisionAction.revise:
        return HumanInteractionRequestStatus.modified
    if action in {HumanInteractionDecisionAction.block, HumanInteractionDecisionAction.reject}:
        return HumanInteractionRequestStatus.rejected
    if action == HumanInteractionDecisionAction.skip:
        return HumanInteractionRequestStatus.skipped
    raise RuntimeError(f"unsupported human decision action: {action}")


def build_expired_human_decision_payload(*, expired_at: datetime) -> dict[str, str]:
    return {
        "action": "expired",
        "summary": EXPIRED_HUMAN_DECISION_SUMMARY,
        "decided_at": expired_at.isoformat(),
    }
