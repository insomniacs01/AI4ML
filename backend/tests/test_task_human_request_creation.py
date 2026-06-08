from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import InteractionAssigneeType, TaskHumanRequestCreateRequest, WorkflowStage
from backend.app.services.task_human_request_creation import build_human_request_creation


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _member(user_id: str, role: str = "member", *, status: str = "active") -> TeamMemberRecord:
    return TeamMemberRecord(
        team_id="team-1",
        user_id=user_id,
        role=role,
        member_status=status,
    )


def _payload(**overrides) -> TaskHumanRequestCreateRequest:
    values = {
        "stage": WorkflowStage.data_analysis,
        "request_type": "data_review",
        "title": "Confirm data",
        "summary": "Check target column.",
        "suggested_action": "Approve or revise.",
        "artifact_paths": ["input.csv"],
        "details": {"priority": "high"},
    }
    values.update(overrides)
    return TaskHumanRequestCreateRequest(**values)


def test_build_human_request_creation_defaults_to_requesting_member() -> None:
    creation = build_human_request_creation(
        _payload(timeout_minutes=30),
        requested_by="requester-1",
        actor_role="developer_user",
        team_members=[_member("requester-1", "developer_user")],
        now=NOW,
    )

    assert creation.stage == WorkflowStage.data_analysis
    assert creation.assignee_type == InteractionAssigneeType.member
    assert creation.assignee_value == "requester-1"
    assert creation.assigned_to == "requester-1"
    assert creation.timeout_at == datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    assert creation.payload == {
        "request_type": "data_review",
        "title": "Confirm data",
        "summary": "Check target column.",
        "suggested_action": "Approve or revise.",
        "artifact_paths": ["input.csv"],
        "details": {"priority": "high"},
        "created_by_role": "developer_user",
    }


def test_build_human_request_creation_resolves_role_assignee() -> None:
    creation = build_human_request_creation(
        _payload(
            assignee_type=InteractionAssigneeType.role,
            assignee_value="business_user",
            timeout_minutes=None,
        ),
        requested_by="requester-1",
        actor_role="developer_user",
        team_members=[_member("reviewer-1", "business_user")],
        now=NOW,
    )

    assert creation.assignee_type == InteractionAssigneeType.role
    assert creation.assignee_value == "business_user"
    assert creation.assigned_to is None
    assert creation.timeout_at is None


def test_build_human_request_creation_rejects_inactive_member() -> None:
    with pytest.raises(RuntimeError, match="not an active member"):
        build_human_request_creation(
            _payload(assigned_to="reviewer-1"),
            requested_by="requester-1",
            actor_role="developer_user",
            team_members=[_member("reviewer-1", status="removed")],
            now=NOW,
        )
