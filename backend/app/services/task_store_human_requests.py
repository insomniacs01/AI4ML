from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.models.task import TaskHumanRequestRecord, WorkflowStage


class TaskStoreHumanRequestMixin:
    def list_human_requests(self, team_id: str, task_id: str, *, access_token: str) -> list[TaskHumanRequestRecord]:
        return self.human_request_repository.list_human_requests(team_id, task_id, access_token=access_token)

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
        return self.human_request_repository.create_human_request(
            team_id=team_id,
            task_id=task_id,
            stage=stage,
            requested_by=requested_by,
            access_token=access_token,
            assigned_to=assigned_to,
            assignee_type=assignee_type,
            assignee_value=assignee_value,
            timeout_at=timeout_at,
            version_id=version_id,
            payload=payload,
        )

    def get_human_request(
        self,
        team_id: str,
        task_id: str,
        request_id: str,
        *,
        access_token: str,
    ) -> TaskHumanRequestRecord | None:
        return self.human_request_repository.get_human_request(
            team_id,
            task_id,
            request_id,
            access_token=access_token,
        )

    def update_human_request(
        self,
        request: TaskHumanRequestRecord,
        *,
        access_token: str,
    ) -> TaskHumanRequestRecord:
        return self.human_request_repository.update_human_request(request, access_token=access_token)
