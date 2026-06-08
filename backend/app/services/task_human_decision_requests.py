from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import TaskHumanRequestRecord, TaskRecord
from backend.app.services.task_human_access import assert_actor_can_decide_human_request
from backend.app.services.task_human_expiration import expire_human_request, is_overdue_human_request
from backend.app.services.task_human_stages import is_active_request


def require_decidable_human_request(
    task_store: Any,
    task: TaskRecord,
    request_id: str,
    *,
    access_token: str,
    actor_id: str,
    actor_role: str,
    now: datetime | None = None,
) -> TaskHumanRequestRecord:
    request = task_store.get_human_request(task.team_id, task.id, request_id, access_token=access_token)
    if request is None:
        raise ValueError("human request not found")

    checked_at = now or datetime.now(timezone.utc)
    if is_overdue_human_request(request, now=checked_at):
        expire_human_request(request, expired_at=checked_at)
        task_store.update_human_request(request, access_token=access_token)
        raise RuntimeError("human request has expired")
    if not is_active_request(request):
        raise RuntimeError("human request has already been closed")

    assert_actor_can_decide_human_request(request, actor_id=actor_id, actor_role=actor_role)
    return request
