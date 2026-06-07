from __future__ import annotations

from pathlib import Path
from typing import Iterable

from backend.app.models.task import HumanInteractionRequestStatus, TaskRecord
from backend.app.services.task_human_context import get_task_human_loop
from backend.app.services.task_human_request_status import (
    human_request_is_active,
    human_request_is_completed,
    human_request_status_value,
)


CODEX_PLAN_APPROVAL_VERSION_ID = "codex-plan-approval"
CODEX_PLAN_APPROVAL_REQUEST_TYPE = "codex_plan_approval"
CODEX_IMPROVEMENT_REVIEW_VERSION_ID = "codex-improvement-review"
CODEX_IMPROVEMENT_REVIEW_REQUEST_TYPE = "codex_improvement_review"


def has_open_codex_plan_request(requests: Iterable[object]) -> bool:
    return any(
        getattr(request, "version_id", None) == CODEX_PLAN_APPROVAL_VERSION_ID
        and human_request_is_active(request)
        for request in requests
    )


def has_confirmed_codex_plan_request(task: TaskRecord, requests: Iterable[object]) -> bool:
    if _human_loop_has_confirmed_codex_plan(task):
        return True
    return any(_request_confirms_codex_plan(request) for request in requests)


def has_existing_codex_improvement_review_request(
    requests: Iterable[object],
    *,
    version_id: str,
) -> bool:
    for request in requests:
        payload = getattr(request, "payload", None)
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("request_type") != CODEX_IMPROVEMENT_REVIEW_REQUEST_TYPE:
            continue
        if human_request_is_active(request):
            return True
        if getattr(request, "version_id", None) == version_id and human_request_is_completed(request):
            return True
    return False


def codex_improvement_review_version_id(improvement_plan_path: str | None) -> str:
    if not improvement_plan_path:
        return CODEX_IMPROVEMENT_REVIEW_VERSION_ID
    try:
        fingerprint = Path(improvement_plan_path).stat().st_mtime_ns
    except OSError:
        fingerprint = abs(hash(improvement_plan_path))
    return f"{CODEX_IMPROVEMENT_REVIEW_VERSION_ID}:{fingerprint}"


def _human_loop_has_confirmed_codex_plan(task: TaskRecord) -> bool:
    human_loop = get_task_human_loop(task)
    decision_history_value = human_loop.get("decision_history")
    decision_history = decision_history_value if isinstance(decision_history_value, list) else []
    latest_decision_value = human_loop.get("latest_decision")
    latest_decision = latest_decision_value if isinstance(latest_decision_value, dict) else None
    decisions = [item for item in [latest_decision, *decision_history] if isinstance(item, dict)]
    return any(
        item.get("request_type") == CODEX_PLAN_APPROVAL_REQUEST_TYPE
        and item.get("action") in {"approve", "skip"}
        and item.get("resume_task") is not False
        for item in decisions
    )


def _request_confirms_codex_plan(request: object) -> bool:
    if getattr(request, "version_id", None) != CODEX_PLAN_APPROVAL_VERSION_ID:
        return False
    status_value = getattr(request, "status", "")
    status_text = human_request_status_value(status_value)
    decision = getattr(request, "decision", None)
    confirmed_statuses = {
        HumanInteractionRequestStatus.confirmed.value,
        HumanInteractionRequestStatus.skipped.value,
    }
    return (
        status_text in confirmed_statuses
        and isinstance(decision, dict)
        and decision.get("action") in {"approve", "skip"}
    )
