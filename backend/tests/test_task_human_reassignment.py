from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    HumanInteractionDecisionAction,
    HumanInteractionRequestStatus,
    InteractionAssigneeType,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_human_access import ResolvedHumanAssignee
from backend.app.services.task_human_reassignment import reassign_human_request


class _FakeTaskStore:
    def __init__(self) -> None:
        self.updated_requests: list[TaskHumanRequestRecord] = []
        self.created_requests: list[dict] = []

    def update_human_request(self, request: TaskHumanRequestRecord, *, access_token: str):
        self.updated_requests.append(request.model_copy(deep=True))
        return request

    def create_human_request(self, **kwargs):
        self.created_requests.append(kwargs)


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-human-reassignment",
        team_id="team-1",
        created_by="user-1",
        name="Human reassignment",
        description="Reassignment task.",
        status=TaskStatus.paused_for_review,
        created_at=now,
        updated_at=now,
    )


def _request() -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id="request-1",
        team_id="team-1",
        task_id="task-human-reassignment",
        stage=WorkflowStage.data_analysis,
        status=HumanInteractionRequestStatus.open,
        requested_by="user-1",
        assigned_to="reviewer-1",
        assignee_type=InteractionAssigneeType.member,
        assignee_value="reviewer-1",
        version_id="request-version",
        payload={"request_type": "data_review", "title": "Confirm data"},
        created_at=now,
        updated_at=now,
    )


def test_reassign_human_request_closes_original_and_creates_followup() -> None:
    decided_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    store = _FakeTaskStore()
    payload = TaskHumanRequestDecisionRequest(
        action=HumanInteractionDecisionAction.reassign,
        decision_summary="Send to data owner.",
        artifact_paths=["input.csv"],
        reassign_timeout_minutes=30,
    )

    updated = reassign_human_request(
        store,
        _task(),
        _request(),
        payload,
        assignee=ResolvedHumanAssignee(InteractionAssigneeType.role, "data_owner", None),
        decided_by="reviewer-1",
        actor_role="developer_user",
        access_token="token",
        decided_at=decided_at,
    )

    assert updated.status == HumanInteractionRequestStatus.reassigned
    assert updated.decision == {
        "action": "reassign",
        "summary": "Send to data owner.",
        "artifact_paths": ["input.csv"],
        "details": None,
        "decided_by": "reviewer-1",
        "decided_by_role": "developer_user",
        "decided_at": "2026-01-02T03:04:05+00:00",
        "reassigned_to": {
            "assignee_type": "role",
            "assignee_value": "data_owner",
            "assigned_to": None,
        },
    }
    assert store.updated_requests == [updated]

    created = store.created_requests[0]
    assert created["stage"] == WorkflowStage.data_analysis
    assert created["requested_by"] == "reviewer-1"
    assert created["assigned_to"] is None
    assert created["assignee_type"] == "role"
    assert created["assignee_value"] == "data_owner"
    assert created["timeout_at"] == datetime(2026, 1, 2, 3, 34, 5, tzinfo=timezone.utc)
    assert created["version_id"] == "request-version:reassigned:1767323045"
    assert created["payload"] == {
        "request_type": "data_review",
        "title": "Confirm data",
        "reassigned_from_request_id": "request-1",
        "reassigned_by": "reviewer-1",
        "reassigned_by_role": "developer_user",
        "reassign_reason": "Send to data owner.",
        "previous_assignee_type": "member",
        "previous_assignee_value": "reviewer-1",
    }
    assert created["access_token"] == "token"
