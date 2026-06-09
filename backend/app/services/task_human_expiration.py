from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestRecord,
    TaskRecord,
)
from backend.app.services.task_human_stages import is_active_request
from backend.app.services.task_human_transitions import build_expired_human_decision_payload


def is_overdue_human_request(request: TaskHumanRequestRecord, *, now: datetime | None = None) -> bool:
    checked_at = now or datetime.now(timezone.utc)
    return request.timeout_at is not None and is_active_request(request) and request.timeout_at <= checked_at


def expire_human_request(request: TaskHumanRequestRecord, *, expired_at: datetime) -> TaskHumanRequestRecord:
    request.status = HumanInteractionRequestStatus.expired
    request.decision = build_expired_human_decision_payload(expired_at=expired_at)
    return request


def expire_overdue_human_requests(
    task_store: Any,
    task: TaskRecord,
    *,
    access_token: str,
    prefer_cache: bool = False,
    allow_stale_cache: bool = False,
) -> list[TaskHumanRequestRecord]:
    list_kwargs: dict[str, Any] = {"access_token": access_token}
    if prefer_cache or allow_stale_cache:
        list_kwargs["prefer_cache"] = prefer_cache
        list_kwargs["allow_stale_cache"] = allow_stale_cache
    requests = task_store.list_human_requests(
        task.team_id,
        task.id,
        **list_kwargs,
    )
    now = datetime.now(timezone.utc)
    if allow_stale_cache and any(is_overdue_human_request(request, now=now) for request in requests):
        requests = task_store.list_human_requests(
            task.team_id,
            task.id,
            access_token=access_token,
        )
    expired_any = False
    for request in requests:
        if not is_overdue_human_request(request, now=now):
            continue
        expire_human_request(request, expired_at=now)
        task_store.update_human_request(request, access_token=access_token)
        expired_any = True
    if not expired_any:
        return requests
    return task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
