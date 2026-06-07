from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord


LOWER_IS_BETTER_METRICS = {
    "rmse",
    "root_mean_squared_error",
    "mse",
    "mean_squared_error",
    "mae",
    "mean_absolute_error",
    "median_absolute_error",
    "log_loss",
    "pinball_loss",
}
CLASSIFICATION_METRICS = {"accuracy", "balanced_accuracy", "f1"}
REGRESSION_METRICS = {"rmse", "root_mean_squared_error", "mse", "mean_squared_error", "mae", "mean_absolute_error", "r2"}


def baseline_completed(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") == "completed" and isinstance(value.get("metric_value"), (int, float))


def resolve_metric_name(task: TaskRecord) -> str:
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    metric_name = requirements.get("metric_name")
    if isinstance(metric_name, str) and metric_name.strip():
        return metric_name.strip().lower()
    if task.last_run and task.last_run.metric_name:
        return task.last_run.metric_name
    return ""


def metric_snapshot(payload: Any) -> dict[str, Any] | None:
    if not baseline_completed(payload):
        return None
    return {
        "metric_name": payload.get("metric_name"),
        "metric_value": payload.get("metric_value"),
        "validation_score": payload.get("validation_score"),
    }


def compare_metric(
    model_metric_name: str,
    model_value: float,
    baseline_metric_name: str,
    baseline_value: float,
) -> dict[str, Any] | None:
    model_key = normalize_metric(model_metric_name)
    baseline_key = normalize_metric(baseline_metric_name)
    if model_key != baseline_key:
        return None
    lower_better = is_lower_better(model_key)
    if lower_better:
        delta = baseline_value - model_value
        denominator = abs(baseline_value) if abs(baseline_value) > 1e-12 else 1.0
        better = delta > max(denominator * 0.01, 1e-12)
    else:
        delta = model_value - baseline_value
        denominator = abs(baseline_value) if abs(baseline_value) > 1e-12 else 1.0
        better = delta > max(denominator * 0.01, 1e-12)
    return {
        "model_value": model_value,
        "baseline_value": baseline_value,
        "delta": delta,
        "relative_delta": delta / denominator,
        "better": better,
        "direction": "lower" if lower_better else "higher",
    }


def normalize_metric(metric_name: str | None) -> str:
    return str(metric_name or "").strip().lower().replace("-", "_").replace(" ", "_")


def baseline_metric_name(task: TaskRecord) -> str:
    metric_name = resolve_metric_name(task)
    metric_key = normalize_metric(metric_name)
    if task.problem_type == "regression":
        return metric_key if metric_key in REGRESSION_METRICS else "rmse"
    return metric_key if metric_key in CLASSIFICATION_METRICS else "accuracy"


def validation_score(metric_name: str, value: float) -> float:
    return -value if is_lower_better(metric_name) else value


def is_lower_better(metric_name: str) -> bool:
    return normalize_metric(metric_name) in LOWER_IS_BETTER_METRICS


def resolve_regression_metric(metric_name: str, scores: dict[str, float]) -> tuple[str, float]:
    metric_key = normalize_metric(metric_name)
    if metric_key in {"mae", "mean_absolute_error"}:
        return "mae", scores["mae"]
    if metric_key in {"mse", "mean_squared_error"}:
        return "mse", scores["mse"]
    if metric_key == "r2":
        return "r2", scores["r2"]
    return "rmse", scores["rmse"]


def resolve_classification_metric(metric_name: str, scores: dict[str, float]) -> tuple[str, float]:
    metric_key = normalize_metric(metric_name)
    if metric_key == "balanced_accuracy":
        return "balanced_accuracy", scores["balanced_accuracy"]
    if metric_key == "f1" and "f1" in scores:
        return "f1", scores["f1"]
    return "accuracy", scores["accuracy"]
