from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.task import TaskRecord, WorkflowStage
from backend.app.services.task_human_parameter_application import apply_stage_parameters, extract_parameters


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-human-parameter-application",
        team_id="team-1",
        created_by="user-1",
        name="Human parameter application",
        description="Apply stage parameter rules.",
        created_at=now,
        updated_at=now,
    )


def test_extract_parameters_prefers_nested_parameter_payload() -> None:
    assert extract_parameters({"parameters": {"metric_name": "F1"}, "metric_name": "accuracy"}) == {
        "metric_name": "F1"
    }


def test_extract_parameters_keeps_only_known_flat_keys() -> None:
    assert extract_parameters({"metric_name": "F1", "ignored": "value", "time_limit": "120"}) == {
        "metric_name": "F1",
        "time_limit": "120",
    }


def test_data_analysis_parameters_record_multi_target_definition() -> None:
    task = _task()
    requirements = {"column_names": ["x1", "y1", "y2"]}

    normalized = apply_stage_parameters(
        task,
        requirements,
        WorkflowStage.data_analysis.value,
        {"label_column": "y1,y2", "problem_type": "regression", "metric_name": "MAE"},
    )

    assert normalized == {
        "label_column": "y1,y2",
        "target_columns": ["y1", "y2"],
        "problem_type": "regression",
        "metric_name": "mae",
    }
    assert task.label_column == "y1,y2"
    assert task.problem_type == "regression"
    assert requirements["target_definition"] == {
        "target_mode": "multi_target",
        "target_columns": ["y1", "y2"],
        "source": "human_checkpoint",
    }


def test_feature_parameters_reject_excluded_target_columns() -> None:
    task = _task()
    task.label_column = "target"
    requirements = {"column_names": ["age", "income", "target"]}

    with pytest.raises(RuntimeError, match="Target columns cannot be listed as excluded"):
        apply_stage_parameters(
            task,
            requirements,
            WorkflowStage.feature_engineering.value,
            {"include_columns": ["age"], "exclude_columns": ["target"]},
        )
