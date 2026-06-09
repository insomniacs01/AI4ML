from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.dataset_profile import read_dataset_rows
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
from backend.app.services.task_agent_baseline_scoring import (
    class_distribution,
    classification_scores,
    deterministic_split,
    finite_numeric_values,
    regression_scores,
)
from backend.app.services.task_targets import target_columns_from_task


MAX_BASELINE_ROWS = 50_000
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
    fieldnames, dataset_rows = read_dataset_rows(dataset_path, max_rows=MAX_BASELINE_ROWS)
    if not fieldnames or target_column not in fieldnames:
        return []
    for row in dataset_rows:
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
    numeric_values = finite_numeric_values(raw_values)
    if len(numeric_values) < 5:
        return _baseline_blocked("目标列无法稳定转换为数值，不能计算回归简单对照。")
    train, validation = deterministic_split(numeric_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    prediction = sum(train) / len(train)
    scores = regression_scores(validation, prediction)
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


def _compute_classification_baseline(
    task: TaskRecord,
    raw_values: list[str],
    metric_name: str,
    target_column: str,
) -> dict[str, Any]:
    train, validation = deterministic_split(raw_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    counts = Counter(train)
    majority_label, majority_count = counts.most_common(1)[0]
    scores = classification_scores(train, validation, majority_label)
    resolved_metric, metric_value = resolve_classification_metric(metric_name, scores)
    distribution = class_distribution(counts)
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


def _baseline_blocked(detail: str) -> dict[str, Any]:
    return {"status": "blocked", "detail": detail, "generated_at": _now_iso()}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
