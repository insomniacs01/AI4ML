from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_human_expiration import (
    expire_human_request,
    expire_overdue_human_requests,
    is_overdue_human_request,
)


class _FakeTaskStore:
    def __init__(self, requests: list[TaskHumanRequestRecord]) -> None:
        self.requests = [request.model_copy(deep=True) for request in requests]
        self.updated_requests: list[TaskHumanRequestRecord] = []

    def list_human_requests(self, team_id: str, task_id: str, *, access_token: str):
        return [request.model_copy(deep=True) for request in self.requests]

    def update_human_request(self, request: TaskHumanRequestRecord, *, access_token: str):
        self.updated_requests.append(request.model_copy(deep=True))
        self.requests = [
            request.model_copy(deep=True) if item.id == request.id else item
            for item in self.requests
        ]
        return request


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-human-expiration",
        team_id="team-1",
        created_by="user-1",
        name="Human expiration",
        description="Expiration task.",
        status=TaskStatus.paused_for_review,
        created_at=now,
        updated_at=now,
    )


def _request(
    request_id: str,
    *,
    status: HumanInteractionRequestStatus,
    timeout_at: datetime | None,
) -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id=request_id,
        team_id="team-1",
        task_id="task-human-expiration",
        stage=WorkflowStage.data_analysis,
        status=status,
        requested_by="user-1",
        timeout_at=timeout_at,
        created_at=now,
        updated_at=now,
    )


def test_is_overdue_human_request_requires_active_status_and_elapsed_timeout() -> None:
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    overdue = _request("overdue", status=HumanInteractionRequestStatus.open, timeout_at=now - timedelta(minutes=1))
    future = _request("future", status=HumanInteractionRequestStatus.open, timeout_at=now + timedelta(minutes=1))
    closed = _request("closed", status=HumanInteractionRequestStatus.confirmed, timeout_at=now - timedelta(minutes=1))

    assert is_overdue_human_request(overdue, now=now) is True
    assert is_overdue_human_request(future, now=now) is False
    assert is_overdue_human_request(closed, now=now) is False


def test_expire_human_request_records_expired_decision_payload() -> None:
    expired_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    request = _request("request-1", status=HumanInteractionRequestStatus.open, timeout_at=expired_at)

    expired = expire_human_request(request, expired_at=expired_at)

    assert expired.status == HumanInteractionRequestStatus.expired
    assert expired.decision == {
        "action": "expired",
        "summary": "Request expired before a human decision was submitted.",
        "decided_at": "2026-01-02T03:04:05+00:00",
    }


def test_expire_overdue_human_requests_updates_only_elapsed_active_requests() -> None:
    now = datetime.now(timezone.utc)
    overdue = _request("overdue", status=HumanInteractionRequestStatus.open, timeout_at=now - timedelta(minutes=1))
    future = _request("future", status=HumanInteractionRequestStatus.open, timeout_at=now + timedelta(minutes=1))
    store = _FakeTaskStore([overdue, future])

    requests = expire_overdue_human_requests(store, _task(), access_token="token")

    assert [request.id for request in store.updated_requests] == ["overdue"]
    assert [request.status for request in requests] == [
        HumanInteractionRequestStatus.expired,
        HumanInteractionRequestStatus.open,
    ]
