from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.app.core.config import Settings
from backend.app.models.task import (
    HumanInteractionRequestStatus,
    RunSummary,
    TaskCreateRequest,
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskInteractionPolicyInput,
    TaskInteractionPolicyRecord,
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    TokenUsageReport,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.token_usage import ensure_task_runtime_token_usage, get_task_analysis_token_usage


class TaskStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dataset_root_dir = settings.storage_dir
        self.run_output_dir = settings.run_output_dir
        self.dataset_root_dir.mkdir(parents=True, exist_ok=True)
        self.run_output_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self, team_id: str, *, access_token: str) -> list[TaskRecord]:
        payload = self._request_json(
            path=(
                "ai_tasks"
                f"?select={self._task_list_select()}&team_id=eq.{quote(team_id, safe='')}"
                "&order=created_at.desc"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task list response from Supabase.")
        return [self._task_from_payload(item) for item in payload]

    @staticmethod
    def _task_list_select() -> str:
        return ",".join(
            [
                "id",
                "team_id",
                "created_by",
                "creator_user_id",
                "name",
                "description",
                "workflow_id",
                "label_column",
                "problem_type",
                "status",
                "dataset_filename",
                "dataset_path",
                "notes",
                "analysis_token_usage",
                "last_run",
                "last_run_attempt",
                "routing_policy_id",
                "routing_source",
                "stage_routing",
                "interaction_policies",
                "created_at",
                "updated_at",
            ]
        )

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
                "stage_routing": self._serialize_stage_routing_inputs(payload.stage_routing),
                "interaction_policies": self._serialize_interaction_policy_inputs(payload.interaction_policies),
            },
        )
        task = self._task_from_payload(self._unwrap_single_record(created_payload, "task create"))
        self._write_task_manifest(task)
        return task

    def get_task(self, team_id: str, task_id: str, *, access_token: str) -> TaskRecord | None:
        payload = self._request_json(
            path=(
                "ai_tasks"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&id=eq.{quote(task_id, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected task detail response from Supabase.")
        if not payload:
            return None
        return self._task_from_payload(payload[0])

    def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        updated_payload = self._request_json(
            path=(
                "ai_tasks"
                f"?team_id=eq.{quote(task.team_id, safe='')}"
                f"&id=eq.{quote(task.id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body=self._task_to_payload(task),
        )
        saved_task = self._task_from_payload(self._unwrap_single_record(updated_payload, "task update"))
        self._write_task_manifest(saved_task)
        return saved_task

    def save_dataset(self, team_id: str, task_id: str, filename: str, content: bytes) -> Path:
        task_dir = self._task_dir(team_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        if suffix != ".csv":
            raise ValueError(f"dataset filename must end with .csv: {filename}")
        dataset_path = task_dir / "dataset.csv"
        dataset_path.write_bytes(content)
        return dataset_path

    def save_dataset_chunks(self, team_id: str, task_id: str, filename: str, chunks: Iterable[bytes]) -> Path:
        dataset_path = self.dataset_upload_path(team_id, task_id, filename)
        with dataset_path.open("wb") as handle:
            for chunk in chunks:
                if chunk:
                    handle.write(chunk)
        return dataset_path

    def dataset_upload_path(self, team_id: str, task_id: str, filename: str) -> Path:
        task_dir = self._task_dir(team_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        if suffix != ".csv":
            raise ValueError(f"dataset filename must end with .csv: {filename}")
        return task_dir / "dataset.csv"

    def delete_task(self, team_id: str, task_id: str, *, access_token: str) -> bool:
        existing = self.get_task(team_id, task_id, access_token=access_token)
        if existing is None:
            return False

        self._request_json(
            path=(
                "ai_tasks"
                f"?team_id=eq.{quote(team_id, safe='')}"
                f"&id=eq.{quote(task_id, safe='')}"
            ),
            access_token=access_token,
            method="DELETE",
            expect_json=False,
        )
        shutil.rmtree(self._task_dir(team_id, task_id), ignore_errors=True)
        shutil.rmtree(self.run_output_dir / task_id, ignore_errors=True)
        return True

    def list_stage_records(self, team_id: str, task_id: str, *, access_token: str) -> list[WorkflowStageRecord]:
        payload = self._request_json(
            path=(
                "workflow_stage_records"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                "&order=updated_at.desc"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected workflow stage response from Supabase.")

        latest_by_stage: dict[str, WorkflowStageRecord] = {}
        for item in payload:
            record = self._stage_record_from_payload(item)
            stage_key = self._enum_value(record.stage)
            if stage_key not in latest_by_stage:
                latest_by_stage[stage_key] = record
        return list(latest_by_stage.values())

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
            path=(
                "workflow_stage_records"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                f"&stage=eq.{quote(self._enum_value(normalized_stage), safe='')}"
                "&order=updated_at.desc"
                "&limit=1"
            ),
            access_token=access_token,
        )
        existing_record = None
        if isinstance(existing, list) and existing:
            existing_record = self._stage_record_from_payload(existing[0])
        started_at, finished_at, duration_seconds = self._resolve_stage_timing(
            existing_record,
            status=status,
        )
        body = {
            "team_id": team_id,
            "task_id": task_id,
            "stage": self._enum_value(normalized_stage),
            "status": self._enum_value(status),
            "selected_connector_id": selected_connector_id,
            "model_name": model_name,
            "selection_source": selection_source,
            "summary": summary,
            "artifact_refs": artifact_refs,
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": finished_at.isoformat() if finished_at else None,
            "duration_seconds": duration_seconds,
            "log_excerpt": log_excerpt if log_excerpt is not None else (existing_record.log_excerpt if existing_record else None),
        }
        if existing_record is not None:
            updated_payload = self._request_json(
                path=f"workflow_stage_records?id=eq.{quote(existing_record.id, safe='')}",
                access_token=access_token,
                method="PATCH",
                body=body,
            )
            return self._stage_record_from_payload(self._unwrap_single_record(updated_payload, "workflow stage update"))

        created_payload = self._request_json(
            path="workflow_stage_records",
            access_token=access_token,
            method="POST",
            body=body,
        )
        return self._stage_record_from_payload(self._unwrap_single_record(created_payload, "workflow stage create"))

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

    def upsert_run_summary(
        self,
        task: TaskRecord,
        summary: RunSummary,
        *,
        access_token: str,
        status: str = "completed",
        notes: str | None = None,
    ) -> None:
        output_dir = summary.output_dir
        existing = self._request_json(
            path=(
                "task_runs"
                f"?select=id&team_id=eq.{quote(task.team_id, safe='')}"
                f"&task_id=eq.{quote(task.id, safe='')}"
                f"&output_dir=eq.{quote(output_dir, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        body = {
            "team_id": task.team_id,
            "task_id": task.id,
            "status": status,
            "output_dir": output_dir,
            "best_model": summary.best_model,
            "metric_name": summary.metric_name,
            "metric_value": summary.metric_value,
            "leaderboard": summary.leaderboard,
            "token_usage": summary.token_usage.model_dump() if summary.token_usage else None,
            "notes": notes,
            "finished_at": task.updated_at.isoformat(),
        }
        if isinstance(existing, list) and existing:
            self._request_json(
                path=f"task_runs?id=eq.{quote(str(existing[0]['id']), safe='')}",
                access_token=access_token,
                method="PATCH",
                body=body,
            )
            return
        self._request_json(path="task_runs", access_token=access_token, method="POST", body=body)

    def upsert_run_attempt(
        self,
        task: TaskRecord,
        *,
        output_dir: str,
        access_token: str,
        status: str,
        token_usage: TokenUsageReport | None = None,
        notes: str | None = None,
    ) -> None:
        existing = self._request_json(
            path=(
                "task_runs"
                f"?select=id&team_id=eq.{quote(task.team_id, safe='')}"
                f"&task_id=eq.{quote(task.id, safe='')}"
                f"&output_dir=eq.{quote(output_dir, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        body = {
            "team_id": task.team_id,
            "task_id": task.id,
            "status": status,
            "output_dir": output_dir,
            "token_usage": token_usage.model_dump() if token_usage else None,
            "notes": notes,
            "finished_at": task.updated_at.isoformat(),
        }
        if isinstance(existing, list) and existing:
            self._request_json(
                path=f"task_runs?id=eq.{quote(str(existing[0]['id']), safe='')}",
                access_token=access_token,
                method="PATCH",
                body=body,
            )
            return
        self._request_json(path="task_runs", access_token=access_token, method="POST", body=body)

    def upsert_token_ledger(
        self,
        *,
        team_id: str,
        task_id: str,
        phase: str,
        source_key: str,
        usage: TokenUsageReport | None,
        access_token: str,
        user_id: str | None = None,
        connector_id: str | None = None,
        connector_display_name: str | None = None,
        model_name: str | None = None,
        stage_key: str | None = None,
        calculation_method: str | None = None,
    ) -> None:
        if usage is None:
            return

        existing = self._request_json(
            path=(
                "token_ledgers"
                f"?select=id,total_tokens&team_id=eq.{quote(team_id, safe='')}"
                f"&task_id=eq.{quote(task_id, safe='')}"
                f"&phase=eq.{quote(phase, safe='')}"
                f"&source_key=eq.{quote(source_key, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        previous_total = 0
        if isinstance(existing, list) and existing:
            previous_total = _coerce_non_negative_int(existing[0].get("total_tokens"))

        body = {
            "team_id": team_id,
            "task_id": task_id,
            "user_id": user_id,
            "connector_id": connector_id,
            "connector_display_name": connector_display_name,
            "phase": phase,
            "stage_key": stage_key,
            "source_key": source_key,
            "model_name": model_name,
            "calculation_method": calculation_method,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "raw_usage": usage.model_dump(),
        }
        self._request_json(
            path="token_ledgers?on_conflict=team_id,task_id,phase,source_key",
            access_token=access_token,
            method="POST",
            body=body,
            prefer="resolution=merge-duplicates,return=representation",
        )

        delta = usage.total_tokens - previous_total
        if user_id and delta != 0:
            self._adjust_member_token_usage(
                team_id=team_id,
                user_id=user_id,
                token_delta=delta,
                access_token=access_token,
            )

    def _adjust_member_token_usage(self, *, team_id: str, user_id: str, token_delta: int, access_token: str) -> None:
        self._request_json(
            path="rpc/adjust_member_token_usage",
            access_token=access_token,
            method="POST",
            body={
                "target_team_id": team_id,
                "target_user_id": user_id,
                "token_delta": token_delta,
            },
            expect_json=False,
        )

    def _task_dir(self, team_id: str, task_id: str) -> Path:
        return self.dataset_root_dir / task_id

    def task_storage_uri(self, task_id: str) -> str:
        return f"storage/tasks/{task_id}"

    def run_storage_uri(self, task_id: str, run_id: str) -> str:
        return f"storage/mlzero_runs/{task_id}/{run_id}"

    def _write_task_manifest(self, task: TaskRecord) -> None:
        manifest_dir = self._task_dir(task.team_id, task.id)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "task.json"
        manifest_path.write_text(
            json.dumps(task.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _request_json(
        self,
        *,
        path: str,
        access_token: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        expect_json: bool = True,
        prefer: str | None = None,
    ) -> Any:
        self._ensure_configured()
        url = f"{self.settings.supabase_rest_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "apikey": self.settings.supabase_publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept-Profile": "public",
            "Content-Profile": "public",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Prefer"] = prefer or "return=representation"
            data = json.dumps(body).encode("utf-8")
        elif prefer:
            headers["Prefer"] = prefer

        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.settings.supabase_timeout_seconds) as response:  # noqa: S310
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            if exc.code in (401, 403):
                raise PermissionError("Supabase rejected the task storage request.") from exc
            if "does not exist" in payload:
                raise RuntimeError("Supabase task schema is missing. Apply supabase/schema.sql before using task storage.") from exc
            raise ConnectionError(f"Supabase task request failed with HTTP {exc.code}. Response: {payload or '<empty>'}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ConnectionError("Could not reach Supabase to read or write task records.") from exc

        if not raw_body:
            return None if expect_json else True
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            if expect_json:
                raise ConnectionError("Supabase task response was not valid JSON.") from exc
            return True

    def _ensure_configured(self) -> None:
        if self.settings.supabase_configured:
            return
        raise RuntimeError("Supabase task storage is not configured. Set AI4ML_SUPABASE_URL / AI4ML_SUPABASE_PUBLISHABLE_KEY or keep frontend/.env.local available.")

    @staticmethod
    def _unwrap_single_record(payload: Any, action: str) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        raise ConnectionError(f"Unexpected Supabase response shape during {action}.")

    @classmethod
    def _task_from_payload(cls, payload: dict[str, Any]) -> TaskRecord:
        task = TaskRecord.model_validate(payload)
        task = cls._normalize_task_record(task)
        task = ensure_task_runtime_token_usage(task)
        if task.analysis_token_usage is None:
            task.analysis_token_usage = get_task_analysis_token_usage(task)
        return task

    @classmethod
    def _normalize_task_record(cls, task: TaskRecord) -> TaskRecord:
        normalized_stage_routing: list[TaskStageRoutingRecord] = []
        for item in task.stage_routing:
            payload = item.model_dump()
            payload["stage"] = normalize_workflow_stage(item.stage)
            normalized_stage_routing.append(
                TaskStageRoutingRecord(**payload)
            )
        task.stage_routing = normalized_stage_routing

        normalized_policies: list[TaskInteractionPolicyRecord] = []
        for item in task.interaction_policies:
            payload = item.model_dump()
            payload["stage"] = normalize_workflow_stage(item.stage)
            normalized_policies.append(
                TaskInteractionPolicyRecord(**payload)
            )
        task.interaction_policies = normalized_policies
        return task

    @classmethod
    def _stage_record_from_payload(cls, payload: dict[str, Any]) -> WorkflowStageRecord:
        record = WorkflowStageRecord.model_validate(payload)
        if isinstance(record.stage, WorkflowStage):
            record.stage = normalize_workflow_stage(record.stage)
        else:
            record.stage = normalize_workflow_stage(str(record.stage))
        return record

    @classmethod
    def _agent_runtime_from_payload(cls, payload: dict[str, Any]) -> TaskAgentRuntimeRecord:
        record = TaskAgentRuntimeRecord.model_validate(payload)
        if isinstance(record.stage, WorkflowStage):
            record.stage = normalize_workflow_stage(record.stage)
        else:
            record.stage = normalize_workflow_stage(str(record.stage))
        return record

    @classmethod
    def _agent_event_from_payload(cls, payload: dict[str, Any]) -> TaskAgentEventRecord:
        event_payload = dict(payload)
        if "time" not in event_payload:
            event_payload["time"] = event_payload.get("created_at")
        event_payload["artifact_refs"] = cls._flatten_artifact_refs(event_payload.get("artifact_refs"))
        record = TaskAgentEventRecord.model_validate(event_payload)
        if isinstance(record.stage, WorkflowStage):
            record.stage = normalize_workflow_stage(record.stage)
        else:
            record.stage = normalize_workflow_stage(str(record.stage))
        return record

    @classmethod
    def _agent_message_from_payload(cls, payload: dict[str, Any]) -> TaskAgentMessageRecord:
        message_payload = dict(payload)
        if "time" not in message_payload:
            message_payload["time"] = message_payload.get("created_at")
        message_payload["artifact_refs"] = cls._flatten_artifact_refs(message_payload.get("artifact_refs"))
        if not isinstance(message_payload.get("payload"), dict):
            message_payload["payload"] = None
        record = TaskAgentMessageRecord.model_validate(message_payload)
        if isinstance(record.stage, WorkflowStage):
            record.stage = normalize_workflow_stage(record.stage)
        else:
            record.stage = normalize_workflow_stage(str(record.stage))
        return record

    @staticmethod
    def _resolve_stage_timing(
        existing: WorkflowStageRecord | TaskAgentRuntimeRecord | None,
        *,
        status: WorkflowStageStatus,
    ) -> tuple[datetime | None, datetime | None, float | None]:
        now = datetime.now(timezone.utc)
        started_at = existing.started_at if existing else None
        finished_at = existing.finished_at if existing else None

        if status == WorkflowStageStatus.running:
            if existing is None or existing.status != WorkflowStageStatus.running:
                started_at = now
            finished_at = None
        elif status in {WorkflowStageStatus.completed, WorkflowStageStatus.failed}:
            if started_at is None:
                started_at = existing.created_at if existing else now
            if finished_at is None:
                finished_at = now
        elif status in {WorkflowStageStatus.pending, WorkflowStageStatus.waiting_human}:
            if started_at is None:
                finished_at = None

        duration_seconds = None
        if started_at is not None and finished_at is not None:
            duration_seconds = max((finished_at - started_at).total_seconds(), 0.0)
        return started_at, finished_at, duration_seconds

    @classmethod
    def _human_request_from_payload(cls, payload: dict[str, Any]) -> TaskHumanRequestRecord:
        record = TaskHumanRequestRecord.model_validate(payload)
        if isinstance(record.stage, WorkflowStage):
            record.stage = normalize_workflow_stage(record.stage)
        else:
            record.stage = normalize_workflow_stage(str(record.stage))
        return record

    @classmethod
    def _task_to_payload(cls, task: TaskRecord) -> dict[str, Any]:
        return {
            "name": task.name,
            "description": task.description,
            "workflow_id": task.workflow_id,
            "created_by": task.created_by,
            "creator_user_id": task.creator_user_id or task.created_by,
            "label_column": task.label_column,
            "problem_type": task.problem_type,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "dataset_filename": task.dataset_filename,
            "dataset_path": task.dataset_path,
            "dataset_profile": task.dataset_profile.model_dump(mode="json") if task.dataset_profile else None,
            "notes": task.notes,
            "analysis_token_usage": task.analysis_token_usage.model_dump() if task.analysis_token_usage else None,
            "last_run": task.last_run.model_dump(mode="json") if task.last_run else None,
            "last_run_attempt": task.last_run_attempt.model_dump(mode="json") if task.last_run_attempt else None,
            "routing_policy_id": task.routing_policy_id,
            "routing_source": task.routing_source,
            "structured_requirements": task.structured_requirements,
            "stage_routing": cls._serialize_stage_routing_records(task.stage_routing),
            "interaction_policies": cls._serialize_interaction_policy_records(task.interaction_policies),
        }

    @staticmethod
    def _serialize_stage_routing_inputs(items: list[TaskStageRoutingOverrideInput]) -> list[dict[str, Any]]:
        return [
            {
                "stage": normalize_workflow_stage(item.stage).value,
                "connector_id": item.connector_id,
                "model_name": item.model_name,
                "selection_source": "task_override",
            }
            for item in items
            if item.connector_id
        ]

    @staticmethod
    def _serialize_stage_routing_records(items: list[TaskStageRoutingRecord]) -> list[dict[str, Any]]:
        return [
            {
                "stage": normalize_workflow_stage(item.stage).value,
                "connector_id": item.connector_id,
                "connector_display_name": item.connector_display_name,
                "model_name": item.model_name,
                "fallback_connector_id": item.fallback_connector_id,
                "fallback_connector_display_name": item.fallback_connector_display_name,
                "fallback_model_name": item.fallback_model_name,
                "selection_source": item.selection_source,
            }
            for item in items
        ]

    @staticmethod
    def _serialize_interaction_policy_inputs(items: list[TaskInteractionPolicyInput]) -> list[dict[str, Any]]:
        return [
            {
                "policy_id": item.policy_id or f"{normalize_workflow_stage(item.stage).value}:{index + 1}",
                "enabled": item.enabled,
                "stage": normalize_workflow_stage(item.stage).value,
                "trigger_mode": item.trigger_mode.value,
                "assignee_type": item.assignee_type.value,
                "assignee_value": item.assignee_value,
                "request_type": item.request_type,
                "title": item.title,
                "summary": item.summary,
                "suggested_action": item.suggested_action,
                "timeout_minutes": item.timeout_minutes,
                "artifact_paths": item.artifact_paths,
            }
            for index, item in enumerate(items)
        ]

    @staticmethod
    def _serialize_interaction_policy_records(items: list[TaskInteractionPolicyRecord]) -> list[dict[str, Any]]:
        return [
            {
                "policy_id": item.policy_id,
                "enabled": item.enabled,
                "stage": normalize_workflow_stage(item.stage).value,
                "trigger_mode": item.trigger_mode.value,
                "assignee_type": item.assignee_type.value,
                "assignee_value": item.assignee_value,
                "request_type": item.request_type,
                "title": item.title,
                "summary": item.summary,
                "suggested_action": item.suggested_action,
                "timeout_minutes": item.timeout_minutes,
                "artifact_paths": item.artifact_paths,
            }
            for item in items
        ]

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value

    @staticmethod
    def _flatten_artifact_refs(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, dict):
            flattened: list[str] = []
            for key, item in value.items():
                if isinstance(item, list):
                    flattened.extend(str(child) for child in item if child)
                elif item:
                    flattened.append(f"{key}: {item}")
            return flattened
        return [str(value)]


def _coerce_non_negative_int(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return max(result, 0)
