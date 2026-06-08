from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.models.task import WorkflowStage, WorkflowStageStatus, normalize_workflow_stage


def build_agent_run_payload(
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
    selected_connector_id: str | None,
    model_name: str | None,
    selection_source: str | None,
    artifact_refs: Any | None,
    started_at: datetime | None,
    finished_at: datetime | None,
    duration_seconds: float | None,
    log_excerpt: str | None,
    existing_log_excerpt: str | None,
    worker_id: str | None,
) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "stage": normalize_workflow_stage(stage).value,
        "name": name,
        "role": role,
        "short_role": short_role,
        "status": _enum_value(status),
        "progress": max(0, min(int(progress), 100)),
        "current_task": current_task,
        "selected_connector_id": selected_connector_id,
        "model_name": model_name,
        "selection_source": selection_source,
        "artifact_refs": artifact_refs,
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "duration_seconds": duration_seconds,
        "log_excerpt": log_excerpt if log_excerpt is not None else existing_log_excerpt,
        "worker_id": worker_id,
    }


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
