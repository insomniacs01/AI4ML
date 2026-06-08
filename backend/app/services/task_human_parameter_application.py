from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.models.task import (
    TaskRecord,
    WorkflowStage,
)
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_to_plain
from backend.app.services.task_human_columns import assert_known_columns, column_names
from backend.app.services.task_human_parameter_values import (
    normalize_metric,
    optional_int,
    string_list,
    text_value,
)
from backend.app.services.task_targets import split_target_columns
from backend.app.services.task_uploads import is_csv_upload_filename


KNOWN_PARAMETER_KEYS = {
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


def extract_parameters(details: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    raw_parameters = details.get("parameters")
    if isinstance(raw_parameters, dict):
        return raw_parameters
    return {key: value for key, value in details.items() if key in KNOWN_PARAMETER_KEYS}


def apply_stage_parameters(
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


def _apply_requirement_parameters(requirements: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    notes = string_list(parameters.get("requirement_notes") or parameters.get("notes"))
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
    label_column = text_value(parameters.get("label_column"))
    problem_type = text_value(parameters.get("problem_type"))
    metric_name = normalize_metric(parameters.get("metric_name"))

    normalized: dict[str, Any] = {}
    available_columns = column_names(task, requirements)
    if label_column:
        target_columns = split_target_columns(label_column)
        assert_known_columns(target_columns, available_columns, "target column")
        task.label_column = label_column
        normalized["label_column"] = label_column
        if len(target_columns) > 1:
            requirements["target_columns"] = target_columns
            requirements["target_definition"] = {
                "target_mode": "multi_target",
                "target_columns": target_columns,
                "source": "human_checkpoint",
            }
            normalized["target_columns"] = target_columns
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
    include_columns = string_list(parameters.get("include_columns"))
    exclude_columns = string_list(parameters.get("exclude_columns"))
    available_columns = column_names(task, requirements)
    if include_columns:
        assert_known_columns(include_columns, available_columns, "included feature columns")
    if exclude_columns:
        assert_known_columns(exclude_columns, available_columns, "excluded feature columns")

    target_columns = split_target_columns(task.label_column)
    if target_columns:
        target_set = set(target_columns)
        include_columns = [column for column in include_columns if column not in target_set]
        excluded_targets = [column for column in target_columns if column in exclude_columns]
        if excluded_targets:
            raise RuntimeError("Target columns cannot be listed as excluded feature columns.")

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
    allowed_models = string_list(parameters.get("allowed_models"))
    excluded_models = string_list(parameters.get("excluded_models"))
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
    time_limit = optional_int(parameters.get("time_limit"), minimum=5, maximum=300)
    cv_folds = optional_int(parameters.get("cv_folds"), minimum=2, maximum=20)
    metric_name = normalize_metric(parameters.get("metric_name"))
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
    report_focus = string_list(parameters.get("report_focus"))
    payload = {"report_focus": report_focus}
    requirements["report_constraints"] = payload
    return payload


def _refresh_target_profile(task: TaskRecord, label_column: str, requirements: dict[str, Any]) -> None:
    dataset_path = Path(task.dataset_path) if task.dataset_path else None
    target_columns = split_target_columns(label_column)
    if (
        dataset_path
        and dataset_path.exists()
        and dataset_path.is_file()
        and is_csv_upload_filename(dataset_path.name)
        and len(target_columns) <= 1
    ):
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
