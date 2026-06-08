from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    InteractionAssigneeType,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_human_decision_requests import require_decidable_human_request


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class _FakeTaskStore:
    def __init__(self, request: TaskHumanRequestRecord | None) -> None:
        self.request = request
        self.get_calls: list[tuple[str, str, str, str]] = []
        self.updated_requests: list[TaskHumanRequestRecord] = []
        self.update_tokens: list[str] = []

    def get_human_request(
        self,
        team_id: str,
        task_id: str,
        request_id: str,
        *,
        access_token: str,
    ) -> TaskHumanRequestRecord | None:
        self.get_calls.append((team_id, task_id, request_id, access_token))
        return self.request

    def update_human_request(self, request: TaskHumanRequestRecord, *, access_token: str) -> TaskHumanRequestRecord:
        self.updated_requests.append(request.model_copy(deep=True))
        self.update_tokens.append(access_token)
        return request


def _task() -> TaskRecord:
    return TaskRecord(
        id="task-human-decision",
        team_id="team-1",
        created_by="owner-1",
        name="Human decision",
        description="Validate human request decisions.",
        status=TaskStatus.paused_for_review,
        created_at=NOW,
        updated_at=NOW,
    )


def _request(
    *,
    status: HumanInteractionRequestStatus = HumanInteractionRequestStatus.open,
    timeout_at: datetime | None = None,
    assignee_type: InteractionAssigneeType = InteractionAssigneeType.member,
    assignee_value: str = "reviewer-1",
    assigned_to: str | None = "reviewer-1",
) -> TaskHumanRequestRecord:
    return TaskHumanRequestRecord(
        id="request-1",
        team_id="team-1",
        task_id="task-human-decision",
        stage=WorkflowStage.data_analysis,
        status=status,
        requested_by="owner-1",
        assigned_to=assigned_to,
        assignee_type=assignee_type,
        assignee_value=assignee_value,
        timeout_at=timeout_at,
        created_at=NOW,
        updated_at=NOW,
    )


def test_require_decidable_human_request_returns_active_assigned_request() -> None:
    request = _request()
    store = _FakeTaskStore(request)

    resolved = require_decidable_human_request(
        store,
        _task(),
        "request-1",
        access_token="token",
        actor_id="reviewer-1",
        actor_role="member",
        now=NOW,
    )

    assert resolved is request
    assert store.get_calls == [("team-1", "task-human-decision", "request-1", "token")]
    assert store.updated_requests == []


def test_require_decidable_human_request_expires_overdue_request_before_rejecting() -> None:
    request = _request(timeout_at=NOW - timedelta(minutes=1))
    store = _FakeTaskStore(request)

    with pytest.raises(RuntimeError, match="human request has expired"):
        require_decidable_human_request(
            store,
            _task(),
            "request-1",
            access_token="token",
            actor_id="reviewer-1",
            actor_role="member",
            now=NOW,
        )

    assert request.status == HumanInteractionRequestStatus.expired
    assert request.decision is not None
    assert request.decision["action"] == "expired"
    assert store.updated_requests == [request]
    assert store.update_tokens == ["token"]


def test_require_decidable_human_request_rejects_missing_or_closed_requests() -> None:
    missing_store = _FakeTaskStore(None)
    with pytest.raises(ValueError, match="human request not found"):
        require_decidable_human_request(
            missing_store,
            _task(),
            "missing",
            access_token="token",
            actor_id="reviewer-1",
            actor_role="member",
            now=NOW,
        )

    closed_store = _FakeTaskStore(_request(status=HumanInteractionRequestStatus.confirmed))
    with pytest.raises(RuntimeError, match="human request has already been closed"):
        require_decidable_human_request(
            closed_store,
            _task(),
            "request-1",
            access_token="token",
            actor_id="reviewer-1",
            actor_role="member",
            now=NOW,
        )

    assert closed_store.updated_requests == []


def test_require_decidable_human_request_rejects_unauthorized_actor_without_updating() -> None:
    store = _FakeTaskStore(_request())

    with pytest.raises(PermissionError, match="Only the assigned member"):
        require_decidable_human_request(
            store,
            _task(),
            "request-1",
            access_token="token",
            actor_id="outsider-1",
            actor_role="member",
            now=NOW,
        )

    assert store.updated_requests == []
