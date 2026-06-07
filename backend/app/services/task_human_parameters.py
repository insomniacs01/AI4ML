from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import (
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    normalize_workflow_stage,
)
from backend.app.services.task_agent_loop import refresh_agent_loop_after_analysis
from backend.app.services.task_human_parameter_application import apply_stage_parameters, extract_parameters
from backend.app.services.task_human_parameter_values import (
    HUMAN_PARAMETERS_KEY,
    PARAMETER_HISTORY_KEY,
    ensure_dict as _ensure_dict,
)

RUN_AFFECTING_STAGES = {
    WorkflowStage.data_analysis.value,
    WorkflowStage.feature_engineering.value,
    WorkflowStage.model_selection.value,
    WorkflowStage.training_validation.value,
}


def apply_human_decision_parameters(
    task: TaskRecord,
    request: TaskHumanRequestRecord,
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
) -> bool:
    parameters = extract_parameters(payload.details)
    if not parameters:
        return False

    stage = normalize_workflow_stage(request.stage).value
    requirements = _ensure_requirements(task)
    now = datetime.now(timezone.utc).isoformat()
    normalized = apply_stage_parameters(task, requirements, stage, parameters)

    if not normalized:
        return False

    human_loop = _record_parameter_update(
        task,
        requirements,
        stage=stage,
        normalized=normalized,
        now=now,
        decided_by=decided_by,
        request_id=request.id,
    )
    refreshed_loop = _refresh_agent_loop_for_human_analysis(task, stage=stage, now=now, decided_by=decided_by)
    if refreshed_loop is not None:
        human_loop = refreshed_loop

    _request_parameter_rerun_if_needed(task, stage=stage, human_loop=human_loop, now=now)

    task.notes = f"Human parameters updated for {stage}."
    return True


def _record_parameter_update(
    task: TaskRecord,
    requirements: dict[str, Any],
    *,
    stage: str,
    normalized: dict[str, Any],
    now: str,
    decided_by: str,
    request_id: str,
) -> dict[str, Any]:
    stage_parameters = _ensure_dict(requirements.get(HUMAN_PARAMETERS_KEY))
    stage_parameters[stage] = {
        **normalized,
        "updated_at": now,
        "updated_by": decided_by,
        "request_id": request_id,
    }
    requirements[HUMAN_PARAMETERS_KEY] = stage_parameters
    _append_parameter_history(
        requirements,
        {
            "stage": stage,
            "parameters": normalized,
            "updated_at": now,
            "updated_by": decided_by,
            "request_id": request_id,
        },
    )
    human_loop = _mark_parameter_metadata(requirements, now=now, decided_by=decided_by)
    task.structured_requirements = requirements
    return human_loop


def _refresh_agent_loop_for_human_analysis(
    task: TaskRecord,
    *,
    stage: str,
    now: str,
    decided_by: str,
) -> dict[str, Any] | None:
    if stage != WorkflowStage.data_analysis.value or not task.label_column or not task.problem_type:
        return None

    refresh_agent_loop_after_analysis(task)
    requirements = _ensure_requirements(task)
    human_loop = _mark_parameter_metadata(requirements, now=now, decided_by=decided_by)
    task.structured_requirements = requirements
    return human_loop


def _mark_parameter_metadata(requirements: dict[str, Any], *, now: str, decided_by: str) -> dict[str, Any]:
    human_loop = _ensure_dict(requirements.get("human_loop"))
    human_loop["parameter_updated_at"] = now
    human_loop["parameter_updated_by"] = decided_by
    requirements["human_loop"] = human_loop
    return human_loop


def _request_parameter_rerun_if_needed(
    task: TaskRecord,
    *,
    stage: str,
    human_loop: dict[str, Any],
    now: str,
) -> None:
    if stage not in RUN_AFFECTING_STAGES or (task.last_run is None and task.last_run_attempt is None):
        return

    task.last_run = None
    task.last_run_attempt = None
    task.status = TaskStatus.uploaded if task.dataset_filename else TaskStatus.draft
    human_loop["rerun_requested"] = True
    human_loop["rerun_from_stage"] = stage
    human_loop["rerun_reason"] = "Human-selected node parameters changed the modeling configuration."
    human_loop["rerun_requested_at"] = now


def _ensure_requirements(task: TaskRecord) -> dict[str, Any]:
    requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    task.structured_requirements = requirements
    return requirements


def _append_parameter_history(requirements: dict[str, Any], entry: dict[str, Any]) -> None:
    history = [dict(item) for item in requirements.get(PARAMETER_HISTORY_KEY, []) if isinstance(item, dict)]
    history.append(entry)
    requirements[PARAMETER_HISTORY_KEY] = history[-20:]
