from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunSummary, TaskRecord
from backend.app.services.task_agent_baseline_metrics import (
    baseline_metric_name,
    compare_metric,
    is_lower_better,
    metric_snapshot,
    normalize_metric,
    validation_score,
)


def test_normalize_metric_standardizes_spacing_and_separators() -> None:
    assert normalize_metric(" Mean-Absolute Error ") == "mean_absolute_error"


def test_compare_metric_uses_lower_is_better_direction() -> None:
    comparison = compare_metric("mean absolute error", 0.8, "mean-absolute error", 1.0)

    assert comparison is not None
    assert comparison["direction"] == "lower"
    assert comparison["delta"] == 0.19999999999999996
    assert comparison["better"] is True


def test_compare_metric_returns_none_for_different_metric_keys() -> None:
    assert compare_metric("mae", 0.8, "mean absolute error", 1.0) is None


def test_compare_metric_uses_higher_is_better_direction() -> None:
    comparison = compare_metric("accuracy", 0.82, "accuracy", 0.8)

    assert comparison is not None
    assert comparison["direction"] == "higher"
    assert comparison["delta"] == 0.019999999999999907
    assert comparison["better"] is True


def test_metric_snapshot_only_accepts_completed_numeric_baseline() -> None:
    assert metric_snapshot({"status": "pending", "metric_value": 1.0}) is None
    assert metric_snapshot({"status": "completed", "metric_value": "1.0"}) is None
    assert metric_snapshot({"status": "completed", "metric_name": "rmse", "metric_value": 1.0, "validation_score": -1.0}) == {
        "metric_name": "rmse",
        "metric_value": 1.0,
        "validation_score": -1.0,
    }


def test_baseline_metric_name_resolves_task_metric_and_problem_type_defaults() -> None:
    assert baseline_metric_name(_task(problem_type="regression", metric_name="mean absolute error")) == "mean_absolute_error"
    assert baseline_metric_name(_task(problem_type="regression", metric_name="accuracy")) == "rmse"
    assert baseline_metric_name(_task(problem_type="classification", metric_name="mean absolute error")) == "accuracy"


def test_validation_score_inverts_lower_is_better_metrics() -> None:
    assert is_lower_better("root mean squared error") is True
    assert validation_score("rmse", 2.5) == -2.5
    assert validation_score("accuracy", 0.75) == 0.75


def test_baseline_metric_name_falls_back_to_last_run_metric() -> None:
    task = _task(problem_type="classification", metric_name="")
    task.structured_requirements = {}
    task.last_run = RunSummary(best_model="model-a", metric_name="balanced_accuracy", metric_value=0.5, output_dir="runs/1")

    assert baseline_metric_name(task) == "balanced_accuracy"


def _task(*, problem_type: str, metric_name: str) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Task",
        description="Train a model.",
        problem_type=problem_type,
        structured_requirements={"metric_name": metric_name},
        created_at=now,
        updated_at=now,
    )
