from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from backend.app.api.routes.team import _pause_member_tasks_if_quota_exhausted


def test_pause_member_tasks_if_quota_exhausted_pauses_target_member(monkeypatch) -> None:
    task_store = object()
    pause_member_tasks = Mock()
    monkeypatch.setattr("backend.app.api.routes.team.get_task_store", lambda: task_store)
    monkeypatch.setattr("backend.app.api.routes.team.pause_member_tasks_for_quota", pause_member_tasks)
    quota = SimpleNamespace(status="active", token_quota=100, token_remaining=0)
    team_access = SimpleNamespace(team_id="team-1", access_token="token")

    _pause_member_tasks_if_quota_exhausted(quota, "user-1", team_access)

    pause_member_tasks.assert_called_once_with(task_store, team_access, user_id="user-1")


def test_pause_member_tasks_if_quota_exhausted_ignores_available_quota(monkeypatch) -> None:
    pause_member_tasks = Mock()
    monkeypatch.setattr("backend.app.api.routes.team.pause_member_tasks_for_quota", pause_member_tasks)
    quota = SimpleNamespace(status="active", token_quota=100, token_remaining=10)

    _pause_member_tasks_if_quota_exhausted(quota, "user-1", SimpleNamespace())

    pause_member_tasks.assert_not_called()
