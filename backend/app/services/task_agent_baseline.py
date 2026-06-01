from __future__ import annotations

import csv
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import TaskRecord


MAX_BASELINE_ROWS = 50_000
MAX_PREVIEW_DISTINCT_VALUES = 200
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


def compute_baseline(task: TaskRecord) -> dict[str, Any]:
    if not task.dataset_path or not task.label_column or task.problem_type not in {"classification", "regression"}:
        return pending_baseline("等待数据集、目标列和问题类型齐备后计算简单对照。")
    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists() or not dataset_path.is_file():
        return _baseline_blocked(f"数据集文件不存在，无法计算简单对照：{dataset_path}")
    try:
        rows = _read_target_rows(dataset_path, task.label_column)
    except (OSError, csv.Error, UnicodeError) as exc:
        return _baseline_blocked(f"读取 CSV 失败，无法计算简单对照：{exc}")
    if len(rows) < 5:
        return _baseline_blocked("可用于基线验证的目标值少于 5 行。")
    metric_name = _baseline_metric_name(task)
    if task.problem_type == "regression":
        return _compute_regression_baseline(task, rows, metric_name)
    return _compute_classification_baseline(task, rows, metric_name)


def pending_baseline(detail: str) -> dict[str, Any]:
    return {"status": "pending", "detail": detail, "generated_at": _now_iso()}


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
    lower_better = _is_lower_better(model_key)
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


def _read_target_rows(dataset_path: Path, target_column: str) -> list[str]:
    rows: list[str] = []
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or target_column not in reader.fieldnames:
            return []
        for index, row in enumerate(reader):
            if index >= MAX_BASELINE_ROWS:
                break
            value = row.get(target_column)
            if value is not None and str(value).strip() != "":
                rows.append(str(value).strip())
    return rows


def _compute_regression_baseline(task: TaskRecord, raw_values: list[str], metric_name: str) -> dict[str, Any]:
    numeric_values = _finite_numeric_values(raw_values)
    if len(numeric_values) < 5:
        return _baseline_blocked("目标列无法稳定转换为数值，不能计算回归简单对照。")
    train, validation = _deterministic_split(numeric_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    prediction = sum(train) / len(train)
    scores = _regression_scores(validation, prediction)
    resolved_metric, metric_value = _resolve_regression_metric(metric_name, scores)
    return {
        "status": "completed",
        "method": "mean_target_baseline",
        "label": "均值预测基线",
        "problem_type": "regression",
        "target_column": task.label_column,
        "requested_metric_name": metric_name,
        "metric_name": resolved_metric,
        "metric_value": metric_value,
        "validation_score": _validation_score(resolved_metric, metric_value),
        "direction": "lower" if _is_lower_better(resolved_metric) else "higher",
        "sample_count": len(numeric_values),
        "train_count": len(train),
        "validation_count": len(validation),
        "prediction_value": prediction,
        "generated_at": _now_iso(),
        "notes": [
            "简单对照使用确定性 80/20 划分，仅用训练部分目标均值预测验证部分。",
            "后续模型至少应优于这个简单对照，否则需要进入优化或人工复核。",
        ],
    }


def _finite_numeric_values(raw_values: list[str]) -> list[float]:
    numeric_values: list[float] = []
    for value in raw_values:
        try:
            numeric = float(value)
        except ValueError:
            continue
        if math.isfinite(numeric):
            numeric_values.append(numeric)
    return numeric_values


def _regression_scores(validation: list[float], prediction: float) -> dict[str, float]:
    errors = [value - prediction for value in validation]
    squared_errors = [error * error for error in errors]
    mean_validation = sum(validation) / len(validation)
    total_ss = sum((value - mean_validation) ** 2 for value in validation)
    residual_ss = sum(squared_errors)
    return {
        "rmse": math.sqrt(residual_ss / len(errors)),
        "mae": sum(abs(error) for error in errors) / len(errors),
        "mse": residual_ss / len(errors),
        "r2": 1 - residual_ss / total_ss if total_ss > 0 else 0.0,
    }


def _resolve_regression_metric(metric_name: str, scores: dict[str, float]) -> tuple[str, float]:
    metric_key = normalize_metric(metric_name)
    if metric_key in {"mae", "mean_absolute_error"}:
        return "mae", scores["mae"]
    if metric_key in {"mse", "mean_squared_error"}:
        return "mse", scores["mse"]
    if metric_key == "r2":
        return "r2", scores["r2"]
    return "rmse", scores["rmse"]


def _compute_classification_baseline(task: TaskRecord, raw_values: list[str], metric_name: str) -> dict[str, Any]:
    train, validation = _deterministic_split(raw_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    counts = Counter(train)
    majority_label, majority_count = counts.most_common(1)[0]
    scores = _classification_scores(train, validation, majority_label)
    resolved_metric, metric_value = _resolve_classification_metric(metric_name, scores)
    distribution = _class_distribution(counts)
    return {
        "status": "completed",
        "method": "majority_class_baseline",
        "label": "多数类预测基线",
        "problem_type": "classification",
        "target_column": task.label_column,
        "requested_metric_name": metric_name,
        "metric_name": resolved_metric,
        "metric_value": metric_value,
        "validation_score": _validation_score(resolved_metric, metric_value),
        "direction": "lower" if _is_lower_better(resolved_metric) else "higher",
        "sample_count": len(raw_values),
        "train_count": len(train),
        "validation_count": len(validation),
        "majority_label": majority_label,
        "majority_ratio": majority_count / len(train),
        "class_distribution": distribution,
        "generated_at": _now_iso(),
        "notes": [
            "简单对照使用确定性 80/20 划分，仅预测训练集中出现最多的类别。",
            "如果正式模型没有明显超过多数类简单对照，应检查类别不均衡、目标列和特征有效性。",
        ],
    }


def _classification_scores(train: list[str], validation: list[str], majority_label: str) -> dict[str, float]:
    predictions = [majority_label for _value in validation]
    accuracy = _accuracy(predictions, validation)
    scores = {
        "accuracy": accuracy,
        "balanced_accuracy": _balanced_accuracy(predictions, validation, accuracy),
    }
    if len(set(train)) == 2:
        scores["f1"] = _binary_f1(predictions, validation, majority_label)
    return scores


def _accuracy(predictions: list[str], validation: list[str]) -> float:
    return sum(1 for prediction, actual in zip(predictions, validation) if prediction == actual) / len(validation)


def _balanced_accuracy(predictions: list[str], validation: list[str], fallback: float) -> float:
    recalls = []
    for label in sorted(set(validation)):
        total = sum(1 for value in validation if value == label)
        correct = sum(1 for prediction, actual in zip(predictions, validation) if actual == label and prediction == actual)
        recalls.append(correct / total if total else 0.0)
    return sum(recalls) / len(recalls) if recalls else fallback


def _binary_f1(predictions: list[str], validation: list[str], positive: str) -> float:
    tp = sum(1 for prediction, actual in zip(predictions, validation) if prediction == positive and actual == positive)
    fp = sum(1 for prediction, actual in zip(predictions, validation) if prediction == positive and actual != positive)
    fn = sum(1 for prediction, actual in zip(predictions, validation) if prediction != positive and actual == positive)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _resolve_classification_metric(metric_name: str, scores: dict[str, float]) -> tuple[str, float]:
    metric_key = normalize_metric(metric_name)
    if metric_key == "balanced_accuracy":
        return "balanced_accuracy", scores["balanced_accuracy"]
    if metric_key == "f1" and "f1" in scores:
        return "f1", scores["f1"]
    return "accuracy", scores["accuracy"]


def _class_distribution(counts: Counter[str]) -> dict[str, int]:
    return {str(label): count for label, count in counts.most_common(MAX_PREVIEW_DISTINCT_VALUES)}


def _deterministic_split(values: list[Any]) -> tuple[list[Any], list[Any]]:
    validation = [value for index, value in enumerate(values) if index % 5 == 0]
    train = [value for index, value in enumerate(values) if index % 5 != 0]
    if not validation and values:
        validation = values[-1:]
        train = values[:-1]
    return train, validation


def _baseline_blocked(detail: str) -> dict[str, Any]:
    return {"status": "blocked", "detail": detail, "generated_at": _now_iso()}


def _baseline_metric_name(task: TaskRecord) -> str:
    metric_name = resolve_metric_name(task)
    metric_key = normalize_metric(metric_name)
    if task.problem_type == "regression":
        return metric_key if metric_key in REGRESSION_METRICS else "rmse"
    return metric_key if metric_key in CLASSIFICATION_METRICS else "accuracy"


def _validation_score(metric_name: str, value: float) -> float:
    return -value if _is_lower_better(metric_name) else value


def _is_lower_better(metric_name: str) -> bool:
    return normalize_metric(metric_name) in LOWER_IS_BETTER_METRICS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
