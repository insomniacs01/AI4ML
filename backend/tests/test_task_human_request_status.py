from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import HumanInteractionRequestStatus, TaskHumanRequestRecord
from backend.app.services.task_human_request_status import (
    human_request_is_active,
    human_request_is_completed,
    human_request_status_value,
)


def _request(status: HumanInteractionRequestStatus) -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id=f"request-{status.value}",
        team_id="team-1",
        task_id="task-1",
        stage="data_analysis",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_human_request_active_statuses_are_pending_and_open() -> None:
    assert human_request_is_active(_request(HumanInteractionRequestStatus.pending)) is True
    assert human_request_is_active(_request(HumanInteractionRequestStatus.open)) is True
    assert human_request_is_active(_request(HumanInteractionRequestStatus.confirmed)) is False
    assert human_request_is_active(_request(HumanInteractionRequestStatus.expired)) is False


def test_human_request_completed_statuses_match_terminal_decisions() -> None:
    assert human_request_is_completed(_request(HumanInteractionRequestStatus.confirmed)) is True
    assert human_request_is_completed(_request(HumanInteractionRequestStatus.modified)) is True
    assert human_request_is_completed(_request(HumanInteractionRequestStatus.rejected)) is True
    assert human_request_is_completed(_request(HumanInteractionRequestStatus.skipped)) is True
    assert human_request_is_completed(_request(HumanInteractionRequestStatus.resolved)) is True
    assert human_request_is_completed(_request(HumanInteractionRequestStatus.pending)) is False
    assert human_request_is_completed(_request(HumanInteractionRequestStatus.expired)) is False


def test_human_request_status_value_normalizes_enums_and_strings() -> None:
    assert human_request_status_value(HumanInteractionRequestStatus.open) == "open"
    assert human_request_status_value(" OPEN ") == "open"
    assert human_request_status_value(None) == ""
