from __future__ import annotations

from backend.app.models.task import HumanInteractionRequestStatus, TaskHumanRequestRecord


ACTIVE_HUMAN_REQUEST_STATUSES = {
    HumanInteractionRequestStatus.pending,
    HumanInteractionRequestStatus.open,
}
COMPLETED_HUMAN_REQUEST_STATUSES = {
    HumanInteractionRequestStatus.confirmed,
    HumanInteractionRequestStatus.modified,
    HumanInteractionRequestStatus.rejected,
    HumanInteractionRequestStatus.skipped,
    HumanInteractionRequestStatus.resolved,
}
ACTIVE_HUMAN_REQUEST_STATUS_VALUES = {status.value for status in ACTIVE_HUMAN_REQUEST_STATUSES}
COMPLETED_HUMAN_REQUEST_STATUS_VALUES = {status.value for status in COMPLETED_HUMAN_REQUEST_STATUSES}


def human_request_status_value(value: object) -> str:
    return str(value.value if hasattr(value, "value") else value or "").strip().lower()


def human_request_is_active(request: TaskHumanRequestRecord) -> bool:
    return human_request_status_value(request.status) in ACTIVE_HUMAN_REQUEST_STATUS_VALUES


def human_request_is_completed(request: TaskHumanRequestRecord) -> bool:
    return human_request_status_value(request.status) in COMPLETED_HUMAN_REQUEST_STATUS_VALUES
