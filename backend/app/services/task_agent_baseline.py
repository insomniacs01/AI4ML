from __future__ import annotations

import csv
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_agent_baseline_metrics import (
    baseline_completed,
    baseline_metric_name,
    compare_metric,
    is_lower_better,
    metric_snapshot,
    normalize_metric,
    resolve_classification_metric,
    resolve_metric_name,
    resolve_regression_metric,
    validation_score,
)
from backend.app.services.task_targets import target_columns_from_task


MAX_BASELINE_ROWS = 50_000
MAX_PREVIEW_DISTINCT_VALUES = 200
__all__ = [
    "baseline_completed",
    "compare_metric",
    "compute_baseline",
    "metric_snapshot",
    "normalize_metric",
    "pending_baseline",
    "resolve_metric_name",
]


def compute_baseline(task: TaskRecord) -> dict[str, Any]:
    target_columns = target_columns_from_task(task)
    if not task.dataset_path or not target_columns or task.problem_type not in {"classification", "regression"}:
        return pending_baseline("等待数据集、目标列和问题类型齐备后计算简单对照。")
    if len(target_columns) > 1:
        return pending_baseline("多目标任务由 Codex 在任务工作区内生成基线和评估结果。")
    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists() or not dataset_path.is_file():
        if dataset_path.exists():
            return pending_baseline("当前数据路径是目录，简单对照由 Codex 根据目录内容生成。")
        return _baseline_blocked(f"数据集文件不存在，无法计算简单对照：{dataset_path}")
    target_column = target_columns[0]
    try:
        rows = _read_target_rows(dataset_path, target_column)
    except (OSError, csv.Error, UnicodeError) as exc:
        return _baseline_blocked(f"读取 CSV 失败，无法计算简单对照：{exc}")
    if len(rows) < 5:
        return _baseline_blocked("可用于基线验证的目标值少于 5 行。")
    metric_name = baseline_metric_name(task)
    if task.problem_type == "regression":
        return _compute_regression_baseline(task, rows, metric_name, target_column)
    return _compute_classification_baseline(task, rows, metric_name, target_column)


def pending_baseline(detail: str) -> dict[str, Any]:
    return {"status": "pending", "detail": detail, "generated_at": _now_iso()}


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


def _compute_regression_baseline(
    task: TaskRecord,
    raw_values: list[str],
    metric_name: str,
    target_column: str,
) -> dict[str, Any]:
    numeric_values = _finite_numeric_values(raw_values)
    if len(numeric_values) < 5:
        return _baseline_blocked("目标列无法稳定转换为数值，不能计算回归简单对照。")
    train, validation = _deterministic_split(numeric_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    prediction = sum(train) / len(train)
    scores = _regression_scores(validation, prediction)
    resolved_metric, metric_value = resolve_regression_metric(metric_name, scores)
    return {
        "status": "completed",
        "method": "mean_target_baseline",
        "label": "均值预测基线",
        "problem_type": "regression",
        "target_column": target_column,
        "requested_metric_name": metric_name,
        "metric_name": resolved_metric,
        "metric_value": metric_value,
        "validation_score": validation_score(resolved_metric, metric_value),
        "direction": "lower" if is_lower_better(resolved_metric) else "higher",
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


def _compute_classification_baseline(
    task: TaskRecord,
    raw_values: list[str],
    metric_name: str,
    target_column: str,
) -> dict[str, Any]:
    train, validation = _deterministic_split(raw_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    counts = Counter(train)
    majority_label, majority_count = counts.most_common(1)[0]
    scores = _classification_scores(train, validation, majority_label)
    resolved_metric, metric_value = resolve_classification_metric(metric_name, scores)
    distribution = _class_distribution(counts)
    return {
        "status": "completed",
        "method": "majority_class_baseline",
        "label": "多数类预测基线",
        "problem_type": "classification",
        "target_column": target_column,
        "requested_metric_name": metric_name,
        "metric_name": resolved_metric,
        "metric_value": metric_value,
        "validation_score": validation_score(resolved_metric, metric_value),
        "direction": "lower" if is_lower_better(resolved_metric) else "higher",
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
