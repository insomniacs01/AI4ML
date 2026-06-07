from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    InteractionAssigneeType,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_human_snapshot import (
    build_human_collaboration_snapshot,
    count_open_human_requests,
    visible_human_requests_for_actor,
)


def _task(*, status: TaskStatus = TaskStatus.paused_for_review) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-human-snapshot",
        team_id="team-1",
        created_by="user-1",
        name="Human snapshot",
        description="Snapshot task.",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _request(
    request_id: str,
    *,
    status: HumanInteractionRequestStatus,
    assigned_to: str | None = None,
    assignee_type: InteractionAssigneeType | None = None,
    assignee_value: str | None = None,
) -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id=request_id,
        team_id="team-1",
        task_id="task-human-snapshot",
        stage=WorkflowStage.data_analysis,
        status=status,
        requested_by="requester-1",
        assigned_to=assigned_to,
        assignee_type=assignee_type,
        assignee_value=assignee_value,
        created_at=now,
        updated_at=now,
    )


def test_count_open_human_requests_counts_pending_and_open_only() -> None:
    requests = [
        _request("pending", status=HumanInteractionRequestStatus.pending),
        _request("open", status=HumanInteractionRequestStatus.open),
        _request("confirmed", status=HumanInteractionRequestStatus.confirmed),
    ]

    assert count_open_human_requests(requests) == 2


def test_visible_human_requests_for_actor_filters_member_assignments() -> None:
    assigned = _request(
        "assigned",
        status=HumanInteractionRequestStatus.open,
        assigned_to="reviewer-1",
        assignee_type=InteractionAssigneeType.member,
        assignee_value="reviewer-1",
    )
    other = _request(
        "other",
        status=HumanInteractionRequestStatus.open,
        assigned_to="reviewer-2",
        assignee_type=InteractionAssigneeType.member,
        assignee_value="reviewer-2",
    )

    assert visible_human_requests_for_actor(
        [assigned, other],
        actor_id="reviewer-1",
        actor_role="business_user",
    ) == [assigned]


def test_build_human_collaboration_snapshot_counts_actor_requests_and_resume_state() -> None:
    task = _task()
    assigned = _request(
        "assigned",
        status=HumanInteractionRequestStatus.open,
        assigned_to="reviewer-1",
        assignee_type=InteractionAssigneeType.member,
        assignee_value="reviewer-1",
    )
    closed = _request("closed", status=HumanInteractionRequestStatus.confirmed)

    snapshot = build_human_collaboration_snapshot(
        task,
        stages=[],
        requests=[assigned, closed],
        actor_id="reviewer-1",
        actor_role="business_user",
    )

    assert snapshot.open_request_count == 1
    assert snapshot.my_requests == [assigned]
    assert snapshot.my_open_request_count == 1
    assert snapshot.can_resume is False

    resumable = build_human_collaboration_snapshot(
        task,
        stages=[],
        requests=[closed],
        actor_id="reviewer-1",
        actor_role="business_user",
    )

    assert resumable.open_request_count == 0
    assert resumable.can_resume is True
