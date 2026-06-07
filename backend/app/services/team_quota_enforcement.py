from __future__ import annotations

from typing import Any

from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.services.quota_runtime_guard import pause_member_tasks_for_quota, quota_is_exhausted
from backend.app.services.service_registry import get_task_store


def pause_member_tasks_if_quota_exhausted(
    quota: Any,
    member_id: str,
    team_access: TeamAccessContext,
) -> None:
    if not quota_is_exhausted(quota):
        return
    pause_member_tasks_for_quota(get_task_store(), team_access, user_id=member_id)
