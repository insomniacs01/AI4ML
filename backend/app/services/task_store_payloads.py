from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskInteractionPolicyInput,
    TaskInteractionPolicyRecord,
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_store_stage_timing import resolve_stage_timing
from backend.app.services.token_usage import get_task_analysis_token_usage


class TaskPayloadMapper:

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
        return resolve_stage_timing(existing, status=status)

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
            "executor_type": task.executor_type or "codex",
            "codex_workspace_path": task.codex_workspace_path,
            "codex_session_id": task.codex_session_id,
            "codex_thread_id": task.codex_thread_id,
            "codex_status": task.codex_status,
            "codex_started_at": task.codex_started_at.isoformat() if task.codex_started_at else None,
            "codex_finished_at": task.codex_finished_at.isoformat() if task.codex_finished_at else None,
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
