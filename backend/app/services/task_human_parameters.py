from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import (
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    normalize_workflow_stage,
)
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_to_plain
from backend.app.services.task_agent_loop import refresh_agent_loop_after_analysis
from backend.app.services.task_human_parameter_guidance import (
    build_task_human_parameter_guidance_lines,
    resolve_task_run_time_limit,
)
from backend.app.services.task_human_parameter_values import (
    HUMAN_PARAMETERS_KEY,
    PARAMETER_HISTORY_KEY,
    ensure_dict as _ensure_dict,
    normalize_metric as _normalize_metric,
    optional_int as _optional_int,
    string_list as _string_list,
    text_value as _text,
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
    parameters = _extract_parameters(payload.details)
    if not parameters:
        return False

    stage = normalize_workflow_stage(request.stage).value
    requirements = _ensure_requirements(task)
    now = datetime.now(timezone.utc).isoformat()
    normalized = _apply_stage_parameters(task, requirements, stage, parameters)

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


def _apply_stage_parameters(
    task: TaskRecord,
    requirements: dict[str, Any],
    stage: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if stage == WorkflowStage.data_analysis.value:
        return _apply_data_analysis_parameters(task, requirements, parameters)
    if stage == WorkflowStage.feature_engineering.value:
        return _apply_feature_engineering_parameters(task, requirements, parameters)
    if stage == WorkflowStage.model_selection.value:
        return _apply_model_selection_parameters(requirements, parameters)
    if stage == WorkflowStage.training_validation.value:
        return _apply_training_validation_parameters(requirements, parameters)
    if stage == WorkflowStage.report_generation.value:
        return _apply_report_generation_parameters(requirements, parameters)
    if stage == WorkflowStage.requirement_analysis.value:
        return _apply_requirement_parameters(requirements, parameters)
    return {}


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


def _apply_requirement_parameters(requirements: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    notes = _string_list(parameters.get("requirement_notes") or parameters.get("notes"))
    if not notes:
        return {}
    payload = {"requirement_notes": notes}
    requirements["requirement_constraints"] = payload
    return payload


def _apply_data_analysis_parameters(
    task: TaskRecord,
    requirements: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    label_column = _text(parameters.get("label_column"))
    problem_type = _text(parameters.get("problem_type"))
    metric_name = _normalize_metric(parameters.get("metric_name"))

    normalized: dict[str, Any] = {}
    column_names = _column_names(task, requirements)
    if label_column:
        _assert_known_columns([label_column], column_names, "target column")
        task.label_column = label_column
        normalized["label_column"] = label_column
        _refresh_target_profile(task, label_column, requirements)
    if problem_type:
        if problem_type not in {"classification", "regression"}:
            raise RuntimeError("problem_type must be either classification or regression")
        task.problem_type = problem_type
        normalized["problem_type"] = problem_type
    if metric_name:
        requirements["metric_name"] = metric_name
        normalized["metric_name"] = metric_name

    if normalized:
        requirements["analysis_source"] = "human_checkpoint"
        requirements["confidence"] = 1.0
        requirements["human_analysis"] = {
            "label_column": task.label_column,
            "problem_type": task.problem_type,
            "metric_name": requirements.get("metric_name"),
        }
    return normalized


def _apply_feature_engineering_parameters(
    task: TaskRecord,
    requirements: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    include_columns = _string_list(parameters.get("include_columns"))
    exclude_columns = _string_list(parameters.get("exclude_columns"))
    column_names = _column_names(task, requirements)
    if include_columns:
        _assert_known_columns(include_columns, column_names, "included feature columns")
    if exclude_columns:
        _assert_known_columns(exclude_columns, column_names, "excluded feature columns")

    target_column = _text(task.label_column)
    if target_column:
        include_columns = [column for column in include_columns if column != target_column]
        if target_column in exclude_columns:
            raise RuntimeError("The target column cannot be listed as an excluded feature column.")

    overlap = sorted(set(include_columns) & set(exclude_columns))
    if overlap:
        raise RuntimeError(f"Columns cannot be both included and excluded: {', '.join(overlap)}")

    payload = {
        "include_columns": include_columns,
        "exclude_columns": exclude_columns,
    }
    requirements["feature_constraints"] = payload
    return payload


def _apply_model_selection_parameters(requirements: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    allowed_models = _string_list(parameters.get("allowed_models"))
    excluded_models = _string_list(parameters.get("excluded_models"))
    overlap = sorted({item.lower() for item in allowed_models} & {item.lower() for item in excluded_models})
    if overlap:
        raise RuntimeError(f"Models cannot be both allowed and excluded: {', '.join(overlap)}")
    payload = {
        "allowed_models": allowed_models,
        "excluded_models": excluded_models,
    }
    requirements["model_constraints"] = payload
    return payload


def _apply_training_validation_parameters(requirements: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    time_limit = _optional_int(parameters.get("time_limit"), minimum=5, maximum=300)
    cv_folds = _optional_int(parameters.get("cv_folds"), minimum=2, maximum=20)
    metric_name = _normalize_metric(parameters.get("metric_name"))
    payload: dict[str, Any] = {}
    if time_limit is not None:
        payload["time_limit"] = time_limit
    if cv_folds is not None:
        payload["cv_folds"] = cv_folds
    if metric_name:
        payload["metric_name"] = metric_name
        requirements["metric_name"] = metric_name
    requirements["training_constraints"] = payload
    return payload


def _apply_report_generation_parameters(requirements: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    report_focus = _string_list(parameters.get("report_focus"))
    payload = {"report_focus": report_focus}
    requirements["report_constraints"] = payload
    return payload


def _extract_parameters(details: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    raw_parameters = details.get("parameters")
    if isinstance(raw_parameters, dict):
        return raw_parameters
    known_keys = {
        "label_column",
        "problem_type",
        "metric_name",
        "include_columns",
        "exclude_columns",
        "allowed_models",
        "excluded_models",
        "time_limit",
        "cv_folds",
        "report_focus",
        "requirement_notes",
        "notes",
    }
    return {key: value for key, value in details.items() if key in known_keys}


def _ensure_requirements(task: TaskRecord) -> dict[str, Any]:
    requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    task.structured_requirements = requirements
    return requirements


def _append_parameter_history(requirements: dict[str, Any], entry: dict[str, Any]) -> None:
    history = [dict(item) for item in requirements.get(PARAMETER_HISTORY_KEY, []) if isinstance(item, dict)]
    history.append(entry)
    requirements[PARAMETER_HISTORY_KEY] = history[-20:]


def _refresh_target_profile(task: TaskRecord, label_column: str, requirements: dict[str, Any]) -> None:
    dataset_path = Path(task.dataset_path) if task.dataset_path else None
    if dataset_path and dataset_path.exists() and dataset_path.is_file():
        updated_profile = build_dataset_profile(
            dataset_path,
            filename=task.dataset_filename,
            target_column=label_column,
        )
        task.dataset_profile = updated_profile
        requirements["dataset_profile"] = dataset_profile_to_plain(updated_profile)
        return
    if task.dataset_profile is not None:
        task.dataset_profile = task.dataset_profile.model_copy(update={"target_column": label_column})
        requirements["dataset_profile"] = dataset_profile_to_plain(task.dataset_profile)


def _column_names(task: TaskRecord, requirements: dict[str, Any]) -> list[str]:
    for names in (
        _dataset_profile_column_names(task),
        _requirements_column_names(requirements),
        _requirements_profile_column_names(requirements),
        _dataset_header_column_names(task),
    ):
        if names:
            return names
    return []


def _dataset_profile_column_names(task: TaskRecord) -> list[str]:
    if task.dataset_profile is None or not task.dataset_profile.columns:
        return []
    return [column.name for column in task.dataset_profile.columns]


def _requirements_column_names(requirements: dict[str, Any]) -> list[str]:
    return _string_list(requirements.get("column_names"))


def _requirements_profile_column_names(requirements: dict[str, Any]) -> list[str]:
    profile = requirements.get("dataset_profile")
    if not isinstance(profile, dict):
        return []
    profile_columns = profile.get("columns")
    if not isinstance(profile_columns, list):
        return []
    names = [_profile_column_name(column) for column in profile_columns]
    return [name for name in names if name]


def _profile_column_name(column: object) -> str | None:
    if not isinstance(column, dict):
        return None
    name = str(column.get("name", "")).strip()
    return name or None


def _dataset_header_column_names(task: TaskRecord) -> list[str]:
    dataset_path = Path(task.dataset_path) if task.dataset_path else None
    if not dataset_path or not dataset_path.exists() or not dataset_path.is_file():
        return []
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return [str(item) for item in next(reader)]
        except StopIteration:
            return []


def _assert_known_columns(values: list[str], column_names: list[str], label: str) -> None:
    if not column_names:
        return
    unknown = [value for value in values if value not in column_names]
    if unknown:
        raise RuntimeError(
            f"Unknown {label}: {', '.join(unknown)}. Available columns: {', '.join(column_names)}"
        )
