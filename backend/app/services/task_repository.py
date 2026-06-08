from __future__ import annotations

from backend.app.models.task import (
    TaskCreateRequest,
    TaskRecord,
)
from backend.app.services.task_cache import TaskCache
from backend.app.services.task_repository_queries import (
    TASK_LIST_SELECT,
    TASK_SUMMARY_SELECT,
    task_detail_path,
    task_list_path,
    task_mutation_path,
)
from backend.app.services.task_store_payloads import TaskPayloadMapper



class TaskRepository(TaskPayloadMapper):
    def __init__(self, *, http, cache: TaskCache, local_storage) -> None:
        self.http = http
        self.cache = cache
        self.local_storage = local_storage

    def _request_json(self, **kwargs):
        return self.http.request_json(**kwargs)

    def list_tasks(
        self,
        team_id: str,
        *,
        access_token: str,
        lightweight: bool = True,
        limit: int | None = 100,
        offset: int = 0,
        prefer_cache: bool = True,
        allow_stale_cache: bool = False,
    ) -> list[TaskRecord]:
        cached_tasks = self.cache.list_tasks(team_id)
        if prefer_cache and lightweight and cached_tasks:
            if allow_stale_cache or self.cache.has_fresh_team_cache(team_id):
                return cached_tasks

        try:
            payload = self._request_json(
                path=task_list_path(team_id, lightweight=lightweight, limit=limit, offset=offset),
                access_token=access_token,
            )
        except ConnectionError:
            if cached_tasks:
                return cached_tasks
            raise
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task list response from Supabase.")
        tasks = [self._task_from_payload(item) for item in payload]
        self.cache.upsert_tasks(tasks, detail=not lightweight)
        self.cache.prune_team_tasks(team_id, {task.id for task in tasks})
        return tasks

    @staticmethod
    def _task_summary_select() -> str:
        return TASK_SUMMARY_SELECT

    @staticmethod
    def _task_list_select() -> str:
        return TASK_LIST_SELECT

    def create_task(self, payload: TaskCreateRequest, *, team_id: str, created_by: str, access_token: str) -> TaskRecord:
        created_payload = self._request_json(
            path="ai_tasks",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "created_by": created_by,
                "name": payload.name,
                "description": payload.description,
                "label_column": payload.label_column,
                "problem_type": payload.problem_type,
                "status": "draft",
                "executor_type": "codex",
                "structured_requirements": payload.structured_requirements,
                "stage_routing": self._serialize_stage_routing_inputs(payload.stage_routing),
                "interaction_policies": self._serialize_interaction_policy_inputs(payload.interaction_policies),
            },
        )
        task = self._task_from_payload(self._unwrap_single_record(created_payload, "task create"))
        self.cache.upsert_task(task)
        self.local_storage.write_task_manifest(task)
        return task

    def get_task(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        prefer_cache: bool = True,
        allow_stale_cache: bool = False,
    ) -> TaskRecord | None:
        cached_detail = self.cache.get_task(team_id, task_id, require_detail=True)
        cached_task = cached_detail or self.cache.get_task(team_id, task_id)
        if prefer_cache and cached_task is not None:
            has_fresh_detail = cached_detail is not None and self.cache.has_fresh_task_cache(
                team_id,
                task_id,
                require_detail=True,
            )
            if allow_stale_cache or has_fresh_detail:
                return cached_task

        try:
            payload = self._request_json(
                path=task_detail_path(team_id, task_id),
                access_token=access_token,
            )
        except ConnectionError:
            if cached_task is not None:
                return cached_task
            raise
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task detail response from Supabase.")
        if not payload:
            return None
        task = self._task_from_payload(payload[0])
        self.cache.upsert_task(task, detail=True)
        return task

    def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        updated_payload = self._request_json(
            path=task_mutation_path(task.team_id, task.id),
            access_token=access_token,
            method="PATCH",
            body=self._task_to_payload(task),
        )
        saved_task = self._task_from_payload(self._unwrap_single_record(updated_payload, "task update"))
        self.cache.upsert_task(saved_task)
        self.local_storage.write_task_manifest(saved_task)
        return saved_task

    def delete_task(self, team_id: str, task_id: str, *, access_token: str) -> bool:
        existing = self.get_task(team_id, task_id, access_token=access_token)
        if existing is None:
            return False

        self._request_json(
            path=task_mutation_path(team_id, task_id),
            access_token=access_token,
            method="DELETE",
            expect_json=False,
        )
        self.cache.delete_task(team_id, task_id)
        self.local_storage.delete_task_files(team_id, task_id)
        return True
