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



class TaskAgentRepository(TaskPayloadMapper):
    def __init__(self, http) -> None:
        self.http = http

    def _request_json(self, **kwargs):
        return self.http.request_json(**kwargs)

    def list_agent_runs(self, team_id: str, task_id: str, *, access_token: str) -> list[TaskAgentRuntimeRecord]:
        payload = self._request_json(
            path=(
                "task_agent_runs"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                "&order=updated_at.desc"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task agent runs response from Supabase.")

        latest_by_agent: dict[str, TaskAgentRuntimeRecord] = {}
        for item in payload:
            record = self._agent_runtime_from_payload(item)
            if record.agent_id not in latest_by_agent:
                latest_by_agent[record.agent_id] = record
        return list(latest_by_agent.values())

    def upsert_agent_run(
        self,
        *,
        team_id: str,
        task_id: str,
        agent_id: str,
        stage: WorkflowStage,
        name: str,
        role: str,
        short_role: str,
        status: WorkflowStageStatus,
        progress: int,
        current_task: str,
        access_token: str,
        selected_connector_id: str | None = None,
        model_name: str | None = None,
        selection_source: str | None = None,
        artifact_refs: Any | None = None,
        log_excerpt: str | None = None,
        worker_id: str | None = None,
    ) -> TaskAgentRuntimeRecord:
        normalized_stage = normalize_workflow_stage(stage)
        existing = self._request_json(
            path=(
                "task_agent_runs"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                f"&agent_id=eq.{quote(agent_id, safe='')}"
                "&order=updated_at.desc"
                "&limit=1"
            ),
            access_token=access_token,
        )
        existing_record = None
        if isinstance(existing, list) and existing:
            existing_record = self._agent_runtime_from_payload(existing[0])
        started_at, finished_at, duration_seconds = self._resolve_stage_timing(
            existing_record,
            status=status,
        )
        body = {
            "team_id": team_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "stage": self._enum_value(normalized_stage),
            "name": name,
            "role": role,
            "short_role": short_role,
            "status": self._enum_value(status),
            "progress": max(0, min(int(progress), 100)),
            "current_task": current_task,
            "selected_connector_id": selected_connector_id,
            "model_name": model_name,
            "selection_source": selection_source,
            "artifact_refs": artifact_refs,
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "duration_seconds": duration_seconds,
            "log_excerpt": log_excerpt if log_excerpt is not None else (existing_record.log_excerpt if existing_record else None),
            "worker_id": worker_id,
        }
        if existing_record is not None:
            updated_payload = self._request_json(
                path=f"task_agent_runs?id=eq.{quote(existing_record.id, safe='')}",
                access_token=access_token,
                method="PATCH",
                body=body,
            )
            return self._agent_runtime_from_payload(self._unwrap_single_record(updated_payload, "task agent run update"))

        created_payload = self._request_json(
            path="task_agent_runs",
            access_token=access_token,
            method="POST",
            body=body,
        )
        return self._agent_runtime_from_payload(self._unwrap_single_record(created_payload, "task agent run create"))

    def list_agent_events(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        limit: int = 80,
    ) -> list[TaskAgentEventRecord]:
        payload = self._request_json(
            path=(
                "task_agent_events"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                "&order=created_at.desc"
                f"&limit={max(1, min(limit, 200))}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task agent events response from Supabase.")
        return [self._agent_event_from_payload(item) for item in payload]

    def append_agent_event(
        self,
        *,
        team_id: str,
        task_id: str,
        agent_id: str,
        stage: WorkflowStage,
        kind: str,
        status: str,
        text: str,
        access_token: str,
        artifact_refs: Any | None = None,
    ) -> TaskAgentEventRecord:
        created_payload = self._request_json(
            path="task_agent_events",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "stage": normalize_workflow_stage(stage).value,
                "kind": kind,
                "status": status,
                "text": text,
                "artifact_refs": artifact_refs,
            },
        )
        return self._agent_event_from_payload(self._unwrap_single_record(created_payload, "task agent event create"))

    def list_agent_messages(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        limit: int = 120,
    ) -> list[TaskAgentMessageRecord]:
        payload = self._request_json(
            path=(
                "task_agent_messages"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                "&order=created_at.desc"
                f"&limit={max(1, min(limit, 300))}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task agent messages response from Supabase.")
        return [self._agent_message_from_payload(item) for item in payload]

    def append_agent_message(
        self,
        *,
        team_id: str,
        task_id: str,
        from_agent_id: str,
        stage: WorkflowStage,
        message_type: str,
        content: str,
        access_token: str,
        to_agent_id: str | None = None,
        status: str = "sent",
        payload: dict[str, Any] | None = None,
        artifact_refs: Any | None = None,
        correlation_id: str | None = None,
    ) -> TaskAgentMessageRecord:
        if correlation_id:
            existing = self._request_json(
                path=(
                    "task_agent_messages"
                    f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                    f"&task_id=eq.{quote(task_id, safe='')}"
                    f"&correlation_id=eq.{quote(correlation_id, safe='')}"
                    "&limit=1"
                ),
                access_token=access_token,
            )
            if isinstance(existing, list) and existing:
                return self._agent_message_from_payload(existing[0])

        created_payload = self._request_json(
            path="task_agent_messages",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "task_id": task_id,
                "from_agent_id": from_agent_id,
                "to_agent_id": to_agent_id,
                "stage": normalize_workflow_stage(stage).value,
                "message_type": message_type,
                "status": status,
                "content": content,
                "payload": payload,
                "artifact_refs": artifact_refs,
                "correlation_id": correlation_id,
            },
        )
        return self._agent_message_from_payload(self._unwrap_single_record(created_payload, "task agent message create"))
