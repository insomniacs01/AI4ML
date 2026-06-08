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
from backend.app.services.task_human_decisions import apply_human_decision


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class _FakeTaskStore:
    def __init__(self) -> None:
        self.updated_requests: list[TaskHumanRequestRecord] = []
        self.access_tokens: list[str] = []

    def update_human_request(self, request: TaskHumanRequestRecord, *, access_token: str) -> TaskHumanRequestRecord:
        self.updated_requests.append(request.model_copy(deep=True))
        self.access_tokens.append(access_token)
        return request


def _task() -> TaskRecord:
    return TaskRecord(
        id="task-human-decision",
        team_id="team-1",
        created_by="owner-1",
        name="Human decision",
        description="Apply human decisions.",
        status=TaskStatus.paused_for_review,
        created_at=NOW,
        updated_at=NOW,
    )


def _request(stage: WorkflowStage = WorkflowStage.training_validation) -> TaskHumanRequestRecord:
    return TaskHumanRequestRecord(
        id="request-1",
        team_id="team-1",
        task_id="task-human-decision",
        stage=stage,
        status=HumanInteractionRequestStatus.open,
        requested_by="owner-1",
        assigned_to="reviewer-1",
        assignee_type=InteractionAssigneeType.member,
        assignee_value="reviewer-1",
        created_at=NOW,
        updated_at=NOW,
    )


def test_apply_human_decision_confirms_request_without_rerun() -> None:
    store = _FakeTaskStore()
    request = _request()
    payload = TaskHumanRequestDecisionRequest(
        action=HumanInteractionDecisionAction.approve,
        decision_summary="Looks good.",
        artifact_paths=["report.md"],
    )

    applied = apply_human_decision(
        store,
        _task(),
        request,
        payload,
        decided_by="reviewer-1",
        actor_role="developer_user",
        access_token="token",
        decided_at=NOW,
    )

    assert applied.request is request
    assert applied.rerun_from_stage is None
    assert request.status == HumanInteractionRequestStatus.confirmed
    assert request.decision == {
        "action": "approve",
        "summary": "Looks good.",
        "artifact_paths": ["report.md"],
        "details": None,
        "decided_by": "reviewer-1",
        "decided_by_role": "developer_user",
        "decided_at": "2026-01-01T12:00:00+00:00",
        "requires_rerun": False,
        "rerun_from_stage": None,
    }
    assert store.updated_requests == [request]
    assert store.access_tokens == ["token"]


def test_apply_human_decision_marks_revise_for_stage_rerun() -> None:
    store = _FakeTaskStore()
    request = _request(WorkflowStage.model_selection)
    payload = TaskHumanRequestDecisionRequest(
        action=HumanInteractionDecisionAction.revise,
        decision_summary="Try more models.",
    )

    applied = apply_human_decision(
        store,
        _task(),
        request,
        payload,
        decided_by="reviewer-1",
        actor_role="developer_user",
        access_token="token",
        decided_at=NOW,
    )

    assert applied.rerun_from_stage == "model_selection"
    assert request.status == HumanInteractionRequestStatus.modified
    assert request.decision is not None
    assert request.decision["requires_rerun"] is True
    assert request.decision["rerun_from_stage"] == "model_selection"


def test_apply_human_decision_skips_request_without_rerun() -> None:
    store = _FakeTaskStore()
    request = _request()
    payload = TaskHumanRequestDecisionRequest(
        action=HumanInteractionDecisionAction.skip,
        decision_summary="No action needed.",
    )

    applied = apply_human_decision(
        store,
        _task(),
        request,
        payload,
        decided_by="reviewer-1",
        actor_role="developer_user",
        access_token="token",
        decided_at=NOW,
    )

    assert applied.rerun_from_stage is None
    assert request.status == HumanInteractionRequestStatus.skipped
    assert request.decision is not None
    assert request.decision["action"] == "skip"
