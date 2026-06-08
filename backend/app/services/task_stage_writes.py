from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.models.task import WorkflowStage, WorkflowStageStatus, normalize_workflow_stage


def build_stage_record_payload(
    *,
    team_id: str,
    task_id: str,
    stage: WorkflowStage,
    status: WorkflowStageStatus,
    selected_connector_id: str | None,
    model_name: str | None,
    selection_source: str | None,
    summary: str | None,
    artifact_refs: Any | None,
    started_at: datetime | None,
    finished_at: datetime | None,
    duration_seconds: float | None,
    log_excerpt: str | None,
    existing_log_excerpt: str | None,
) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "task_id": task_id,
        "stage": normalize_workflow_stage(stage).value,
        "status": _enum_value(status),
        "selected_connector_id": selected_connector_id,
        "model_name": model_name,
        "selection_source": selection_source,
        "summary": summary,
        "artifact_refs": artifact_refs,
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "duration_seconds": duration_seconds,
        "log_excerpt": log_excerpt if log_excerpt is not None else existing_log_excerpt,
    }


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
