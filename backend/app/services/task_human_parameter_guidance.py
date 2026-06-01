from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord, WorkflowStage
from backend.app.services.task_human_parameter_values import (
    ensure_dict,
    join_list,
    optional_int,
    stage_parameters,
    string_list,
    text_value,
)
from backend.app.services.task_targets import target_columns_display, target_columns_from_task


def build_task_human_parameter_guidance_lines(task: TaskRecord) -> list[str]:
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    lines: list[str] = []

    data_line = _data_analysis_guidance_line(task, requirements)
    if data_line:
        lines.append(data_line)

    feature_line = _feature_engineering_guidance_line(requirements)
    if feature_line:
        lines.append(feature_line)

    model_line = _model_selection_guidance_line(requirements)
    if model_line:
        lines.append(model_line)

    training_line = _training_validation_guidance_line(requirements)
    if training_line:
        lines.append(training_line)

    report_line = _report_generation_guidance_line(requirements)
    if report_line:
        lines.append(report_line)

    return lines


def resolve_task_run_time_limit(task: TaskRecord, requested_time_limit: int | None) -> int | None:
    if requested_time_limit is not None:
        return requested_time_limit
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    constraints = ensure_dict(requirements.get("training_constraints"))
    return optional_int(constraints.get("time_limit"), minimum=5, maximum=300)


def _data_analysis_guidance_line(task: TaskRecord, requirements: dict[str, Any]) -> str:
    data_params = stage_parameters(requirements, WorkflowStage.data_analysis.value)
    target_column = target_columns_display(target_columns_from_task(task)) or text_value(
        data_params.get("label_column") or task.label_column
    )
    problem_type = text_value(data_params.get("problem_type") or task.problem_type)
    metric_name = text_value(data_params.get("metric_name") or requirements.get("metric_name"))
    if not (target_column or problem_type or metric_name):
        return ""
    return (
        "Human node parameters - data analysis: "
        f"target column={target_column or 'not specified'}; "
        f"problem type={problem_type or 'not specified'}; "
        f"primary metric={metric_name or 'not specified'}."
    )


def _feature_engineering_guidance_line(requirements: dict[str, Any]) -> str:
    feature_constraints = ensure_dict(requirements.get("feature_constraints"))
    include_columns = string_list(feature_constraints.get("include_columns"))
    exclude_columns = string_list(feature_constraints.get("exclude_columns"))
    if not (include_columns or exclude_columns):
        return ""

    parts = []
    if include_columns:
        parts.append(f"use only these feature columns when feasible: {join_list(include_columns)}")
    if exclude_columns:
        parts.append(f"exclude these columns from features: {join_list(exclude_columns)}")
    return (
        "Human node parameters - feature engineering: "
        + "; ".join(parts)
        + ". Never use the target column itself as a feature."
    )


def _model_selection_guidance_line(requirements: dict[str, Any]) -> str:
    model_constraints = ensure_dict(requirements.get("model_constraints"))
    allowed_models = string_list(model_constraints.get("allowed_models"))
    excluded_models = string_list(model_constraints.get("excluded_models"))
    if not (allowed_models or excluded_models):
        return ""

    parts = []
    if allowed_models:
        parts.append(f"limit candidate model families to {join_list(allowed_models)} unless impossible")
    if excluded_models:
        parts.append(f"do not train or select {join_list(excluded_models)}")
    return "Human node parameters - model selection: " + "; ".join(parts) + "."


def _training_validation_guidance_line(requirements: dict[str, Any]) -> str:
    training_constraints = ensure_dict(requirements.get("training_constraints"))
    time_limit = optional_int(training_constraints.get("time_limit"), minimum=5, maximum=300)
    cv_folds = optional_int(training_constraints.get("cv_folds"), minimum=2, maximum=20)
    training_metric = text_value(training_constraints.get("metric_name"))
    if time_limit is None and cv_folds is None and not training_metric:
        return ""

    parts = []
    if time_limit is not None:
        parts.append(f"fit time limit={time_limit} seconds")
    if cv_folds is not None:
        parts.append(f"use {cv_folds}-fold cross-validation or the closest supported validation strategy")
    if training_metric:
        parts.append(f"optimize/report metric={training_metric}")
    return "Human node parameters - training validation: " + "; ".join(parts) + "."


def _report_generation_guidance_line(requirements: dict[str, Any]) -> str:
    report_constraints = ensure_dict(requirements.get("report_constraints"))
    report_focus = string_list(report_constraints.get("report_focus"))
    if not report_focus:
        return ""
    return f"Human node parameters - report generation: emphasize {join_list(report_focus)}."
