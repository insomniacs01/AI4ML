from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    TaskCreateRequest,
    TaskRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.task_repository import TaskRepository


class TaskStoreTaskMixin:
    def list_tasks(
        self,
        team_id: str,
        *,
        access_token: str,
        lightweight: bool = True,
        limit: int | None = 100,
        offset: int = 0,
        statuses: tuple[str, ...] | None = None,
        prefer_cache: bool = True,
        allow_stale_cache: bool = False,
    ) -> list[TaskRecord]:
        tasks = self.task_repository.list_tasks(
            team_id,
            access_token=access_token,
            lightweight=lightweight,
            limit=limit,
            offset=offset,
            statuses=statuses,
            prefer_cache=prefer_cache,
            allow_stale_cache=allow_stale_cache,
        )
        if prefer_cache and lightweight and tasks:
            if allow_stale_cache or self.cache.has_fresh_team_cache(team_id):
                self._refresh_task_list_cache_in_background(
                    team_id,
                    access_token=access_token,
                    lightweight=lightweight,
                    limit=limit,
                    offset=offset,
                    statuses=statuses,
                )
        return tasks

    @staticmethod
    def _task_summary_select() -> str:
        return TaskRepository._task_summary_select()

    @staticmethod
    def _task_list_select() -> str:
        return TaskRepository._task_list_select()

    def create_task(self, payload: TaskCreateRequest, *, team_id: str, created_by: str, access_token: str) -> TaskRecord:
        return self.task_repository.create_task(payload, team_id=team_id, created_by=created_by, access_token=access_token)

    def get_task(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        prefer_cache: bool = True,
        allow_stale_cache: bool = False,
    ) -> TaskRecord | None:
        task = self.task_repository.get_task(
            team_id,
            task_id,
            access_token=access_token,
            prefer_cache=prefer_cache,
            allow_stale_cache=allow_stale_cache,
        )
        if prefer_cache and task is not None:
            if allow_stale_cache or self.cache.has_fresh_task_cache(team_id, task_id, require_detail=True):
                self._refresh_task_cache_in_background(team_id, task_id, access_token=access_token)
        return task

    def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        return self.task_repository.save_task(task, access_token=access_token)

    def delete_task(self, team_id: str, task_id: str, *, access_token: str) -> bool:
        return self.task_repository.delete_task(team_id, task_id, access_token=access_token)

    def list_stage_records(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        prefer_cache: bool = True,
        allow_stale_cache: bool = False,
    ) -> list[WorkflowStageRecord]:
        records = self.stage_repository.list_stage_records(
            team_id,
            task_id,
            access_token=access_token,
            prefer_cache=prefer_cache,
            allow_stale_cache=allow_stale_cache,
        )
        if prefer_cache:
            if records and (allow_stale_cache or self.cache.has_fresh_stage_cache(team_id, task_id)):
                self._refresh_stage_records_cache_in_background(team_id, task_id, access_token=access_token)
            elif allow_stale_cache:
                self._refresh_stage_records_cache_in_background(team_id, task_id, access_token=access_token)
        return records

    def upsert_stage_record(
        self,
        *,
        team_id: str,
        task_id: str,
        stage: WorkflowStage,
        status: WorkflowStageStatus,
        access_token: str,
        selected_connector_id: str | None = None,
        model_name: str | None = None,
        selection_source: str | None = None,
        summary: str | None = None,
        artifact_refs: Any | None = None,
        log_excerpt: str | None = None,
    ) -> WorkflowStageRecord:
        return self.stage_repository.upsert_stage_record(
            team_id=team_id,
            task_id=task_id,
            stage=stage,
            status=status,
            access_token=access_token,
            selected_connector_id=selected_connector_id,
            model_name=model_name,
            selection_source=selection_source,
            summary=summary,
            artifact_refs=artifact_refs,
            log_excerpt=log_excerpt,
        )
