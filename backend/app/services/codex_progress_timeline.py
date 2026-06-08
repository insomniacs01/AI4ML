from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.models.task import TaskRunProgressEvent, TaskRunProgressInsight, WorkflowStage
from backend.app.services.codex_common import CODEX_WAITING_STATUSES, workspace_path_from_artifacts
from backend.app.services.codex_progress_state import current_codex_stage


def build_codex_progress_events(progress: dict[str, Any], artifacts: dict[str, Any]) -> list[TaskRunProgressEvent]:
    progress_events = _progress_event_items(artifacts)
    if progress_events:
        return [_event_from_progress_item(item) for item in progress_events][-80:]

    events = [_event_from_progress_step(step) for step in _progress_step_items(progress)]
    if events:
        return events[-80:]
    if artifacts.get("plan"):
        return [
            TaskRunProgressEvent(
                stage=WorkflowStage.data_analysis,
                event_type="plan_ready",
                message="Codex 已写入 output/plan.md。",
                source="codex_workspace",
            )
        ]
    return []


def build_codex_progress_insights(progress: dict[str, Any], artifacts: dict[str, Any]) -> list[TaskRunProgressInsight]:
    status_value = str(progress.get("status") or "")
    severity = "success" if status_value == "completed" else "warning" if status_value in CODEX_WAITING_STATUSES else "info"
    detail = str(progress.get("summary") or "")
    if not detail and artifacts.get("plan"):
        detail = "计划文件已生成，等待确认。"
    if not detail:
        detail = "等待 Codex 写入进度文件。"
    return [
        TaskRunProgressInsight(
            stage=current_codex_stage(status_value, progress, artifacts),
            event_type=f"codex_{status_value or 'unknown'}",
            headline="Codex 状态",
            detail=detail,
            evidence=workspace_path_from_artifacts(artifacts),
            source="codex_progress",
            severity=severity,
        )
    ]


def workflow_stage_from_codex_step(step_id: str) -> WorkflowStage:
    lowered = step_id.lower()
    if "report" in lowered or "artifact" in lowered or "final" in lowered:
        return WorkflowStage.report_generation
    if "model" in lowered or "validation" in lowered or "train" in lowered:
        return WorkflowStage.training_validation
    if "feature" in lowered:
        return WorkflowStage.feature_engineering
    return WorkflowStage.data_analysis


def _progress_event_items(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    progress_events = artifacts.get("progress_events") if isinstance(artifacts.get("progress_events"), list) else []
    return [item for item in progress_events if isinstance(item, dict)]


def _progress_step_items(progress: dict[str, Any]) -> list[dict[str, Any]]:
    steps = progress.get("steps") if isinstance(progress.get("steps"), list) else []
    return [step for step in steps if isinstance(step, dict)]


def _event_from_progress_item(item: dict[str, Any]) -> TaskRunProgressEvent:
    event_type = str(item.get("event") or "progress_event")
    step = str(item.get("step") or item.get("current_step") or event_type)
    message = str(item.get("message") or item.get("summary") or event_type)
    return TaskRunProgressEvent(
        time=_parse_event_time(item.get("ts")),
        stage=workflow_stage_from_codex_step(step),
        event_type=event_type,
        message=message,
        source="codex_progress_event",
    )


def _event_from_progress_step(step: dict[str, Any]) -> TaskRunProgressEvent:
    title = str(step.get("title") or step.get("id") or "Codex step")
    detail = str(step.get("detail") or "")
    return TaskRunProgressEvent(
        stage=workflow_stage_from_codex_step(str(step.get("id") or title)),
        event_type=str(step.get("status") or "codex_step"),
        message=f"{title}: {detail}" if detail else title,
        source="codex_progress",
    )


def _parse_event_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
