from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.models.task import TaskHumanRequestRecord, WorkflowStage


class TaskStoreHumanRequestMixin:
    def list_human_requests(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        prefer_cache: bool = False,
        allow_stale_cache: bool = False,
    ) -> list[TaskHumanRequestRecord]:
        if prefer_cache and self.cache.has_human_request_cache(team_id, task_id):
            if allow_stale_cache or self.cache.has_fresh_human_request_cache(team_id, task_id):
                requests = self.cache.list_human_requests(team_id, task_id)
                self._refresh_human_requests_cache_in_background(team_id, task_id, access_token=access_token)
                return requests

        requests = self.human_request_repository.list_human_requests(team_id, task_id, access_token=access_token)
        if prefer_cache:
            self.cache.replace_human_requests(team_id, task_id, requests)
        return requests

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
        request = self.human_request_repository.create_human_request(
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
        self.cache.invalidate_human_requests(team_id, task_id)
        return request

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
        updated = self.human_request_repository.update_human_request(request, access_token=access_token)
        self.cache.invalidate_human_requests(request.team_id, request.task_id)
        return updated
