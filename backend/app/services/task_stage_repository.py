from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_cache import TaskCache
from backend.app.services.task_stage_repository_paths import (
    stage_record_lookup_path,
    stage_record_update_path,
    stage_records_path,
)
from backend.app.services.task_stage_writes import build_stage_record_payload
from backend.app.services.task_store_payloads import TaskPayloadMapper



class TaskStageRepository(TaskPayloadMapper):
    def __init__(self, *, http, cache: TaskCache) -> None:
        self.http = http
        self.cache = cache

    def _request_json(self, **kwargs):
        return self.http.request_json(**kwargs)

    def list_stage_records(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        prefer_cache: bool = True,
        allow_stale_cache: bool = False,
    ) -> list[WorkflowStageRecord]:
        cached_records = self.cache.list_stage_records(team_id, task_id) if prefer_cache else []
        if prefer_cache:
            if cached_records and (allow_stale_cache or self.cache.has_fresh_stage_cache(team_id, task_id)):
                return cached_records
            if allow_stale_cache:
                return cached_records

        try:
            payload = self._request_json(
                path=stage_records_path(team_id, task_id),
                access_token=access_token,
            )
        except ConnectionError:
            if cached_records:
                return cached_records
            raise
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected workflow stage response from Supabase.")

        latest_by_stage: dict[str, WorkflowStageRecord] = {}
        for item in payload:
            record = self._stage_record_from_payload(item)
            stage_key = self._enum_value(record.stage)
            if stage_key not in latest_by_stage:
                latest_by_stage[stage_key] = record
        records = list(latest_by_stage.values())
        self.cache.upsert_stage_records(records)
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
        normalized_stage = normalize_workflow_stage(stage)
        existing = self._request_json(
            path=stage_record_lookup_path(team_id, task_id, normalized_stage),
            access_token=access_token,
        )
        existing_record = None
        if isinstance(existing, list) and existing:
            existing_record = self._stage_record_from_payload(existing[0])
        started_at, finished_at, duration_seconds = self._resolve_stage_timing(
            existing_record,
            status=status,
        )
        body = build_stage_record_payload(
            team_id=team_id,
            task_id=task_id,
            stage=normalized_stage,
            status=status,
            selected_connector_id=selected_connector_id,
            model_name=model_name,
            selection_source=selection_source,
            summary=summary,
            artifact_refs=artifact_refs,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            log_excerpt=log_excerpt,
            existing_log_excerpt=existing_record.log_excerpt if existing_record else None,
        )
        if existing_record is not None:
            updated_payload = self._request_json(
                path=stage_record_update_path(existing_record.id),
                access_token=access_token,
                method="PATCH",
                body=body,
            )
            record = self._stage_record_from_payload(self._unwrap_single_record(updated_payload, "workflow stage update"))
            self.cache.upsert_stage_records([record])
            return record

        created_payload = self._request_json(
            path="workflow_stage_records",
            access_token=access_token,
            method="POST",
            body=body,
        )
        record = self._stage_record_from_payload(self._unwrap_single_record(created_payload, "workflow stage create"))
        self.cache.upsert_stage_records([record])
        return record
