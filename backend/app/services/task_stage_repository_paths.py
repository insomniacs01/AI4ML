from __future__ import annotations

from urllib.parse import quote

from backend.app.models.task import WorkflowStage, normalize_workflow_stage


def stage_records_path(team_id: str, task_id: str) -> str:
    return (
        "workflow_stage_records"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&task_id=eq.{quote(task_id, safe='')}"
        "&order=updated_at.desc"
    )


def stage_record_lookup_path(team_id: str, task_id: str, stage: WorkflowStage) -> str:
    return (
        f"{stage_records_path(team_id, task_id)}"
        f"&stage=eq.{quote(normalize_workflow_stage(stage).value, safe='')}"
        "&limit=1"
    )


def stage_record_update_path(record_id: str) -> str:
    return f"workflow_stage_records?id=eq.{quote(record_id, safe='')}"
