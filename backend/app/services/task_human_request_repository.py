from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    TokenUsageReport,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_store_payloads import TaskPayloadMapper



class TaskHumanRequestRepository(TaskPayloadMapper):
    def __init__(self, http) -> None:
        self.http = http

    def _request_json(self, **kwargs):
        return self.http.request_json(**kwargs)

    def list_human_requests(self, team_id: str, task_id: str, *, access_token: str) -> list[TaskHumanRequestRecord]:
        payload = self._request_json(
            path=(
                "human_interaction_requests"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                "&order=updated_at.desc"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected human request response from Supabase.")

        requests = [self._human_request_from_payload(item) for item in payload]
        return sorted(
            requests,
            key=lambda item: (
                0 if item.status in {HumanInteractionRequestStatus.pending, HumanInteractionRequestStatus.open} else 1,
                -item.updated_at.timestamp(),
            ),
        )

    def create_human_request(
        self,
        *,
        team_id: str,
        task_id: str,
        stage: WorkflowStage,
        requested_by: str,
        access_token: str,
        assigned_to: str | None = None,
        assignee_type: str | None = None,
        assignee_value: str | None = None,
        timeout_at: datetime | None = None,
        version_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> TaskHumanRequestRecord:
        created_payload = self._request_json(
            path="human_interaction_requests",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "task_id": task_id,
                "stage": self._enum_value(normalize_workflow_stage(stage)),
                "status": HumanInteractionRequestStatus.pending.value,
                "requested_by": requested_by,
                "assigned_to": assigned_to,
                "assignee_type": assignee_type,
                "assignee_value": assignee_value,
                "timeout_at": timeout_at.isoformat() if timeout_at else None,
                "version_id": version_id,
                "payload": payload,
            },
        )
        return self._human_request_from_payload(self._unwrap_single_record(created_payload, "human request create"))

    def get_human_request(
        self,
        team_id: str,
        task_id: str,
        request_id: str,
        *,
        access_token: str,
    ) -> TaskHumanRequestRecord | None:
        payload = self._request_json(
            path=(
                "human_interaction_requests"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                f"&id=eq.{quote(request_id, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected human request detail response from Supabase.")
        if not payload:
            return None
        return self._human_request_from_payload(payload[0])

    def update_human_request(
        self,
        request: TaskHumanRequestRecord,
        *,
        access_token: str,
    ) -> TaskHumanRequestRecord:
        updated_payload = self._request_json(
            path=(
                "human_interaction_requests"
                f"?team_id=eq.{quote(request.team_id, safe='')}"
                f"&task_id=eq.{quote(request.task_id, safe='')}"
                f"&id=eq.{quote(request.id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body={
                "stage": self._enum_value(normalize_workflow_stage(request.stage)),
                "status": self._enum_value(request.status),
                "requested_by": request.requested_by,
                "assigned_to": request.assigned_to,
                "assignee_type": self._enum_value(request.assignee_type) if request.assignee_type else None,
                "assignee_value": request.assignee_value,
                "timeout_at": request.timeout_at.isoformat() if request.timeout_at else None,
                "version_id": request.version_id,
                "payload": request.payload,
                "decision": request.decision,
            },
        )
        return self._human_request_from_payload(self._unwrap_single_record(updated_payload, "human request update"))
