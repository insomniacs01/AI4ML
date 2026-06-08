from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_report_formatting import (
    coerce_float,
    format_metric_value,
)


def codex_result_summary(task: TaskRecord, metrics: dict[str, Any]) -> list[str]:
    selected = metrics.get("selected_model") if isinstance(metrics.get("selected_model"), dict) else {}
    metric_name, metric_value = _codex_summary_metric(task, selected)
    lines = []
    best_model = _codex_summary_best_model(task, selected)
    if best_model:
        lines.append(f"最佳模型：{best_model}")
    if metric_name:
        lines.append(f"评价指标：{metric_name} = {format_metric_value(metric_value)}")
    rationale = _codex_summary_rationale(selected)
    if rationale:
        lines.append(rationale)
    return lines


def _codex_summary_metric(task: TaskRecord, selected: dict[str, Any]) -> tuple[str, float | None]:
    if task.last_run:
        return task.last_run.metric_name, task.last_run.metric_value
    return _selected_model_metric(selected)


def _selected_model_metric(selected: dict[str, Any]) -> tuple[str, float | None]:
    for container_name in ("cross_validation", "holdout"):
        metric_name, metric_value = _metric_from_container(selected.get(container_name))
        if metric_name:
            return metric_name, metric_value
    return "", None


def _metric_from_container(container: Any) -> tuple[str, float | None]:
    if not isinstance(container, dict):
        return "", None
    for candidate in ("macro_f1_mean", "accuracy_mean", "macro_f1", "accuracy", "r2", "rmse", "mae"):
        value = coerce_float(container.get(candidate))
        if value is not None:
            return candidate, value
    return "", None


def _codex_summary_best_model(task: TaskRecord, selected: dict[str, Any]) -> str | None:
    selected_name = selected.get("name")
    if isinstance(selected_name, str):
        return selected_name
    return task.last_run.best_model if task.last_run else None


def _codex_summary_rationale(selected: dict[str, Any]) -> str:
    rationale = selected.get("selection_rationale")
    return rationale.strip() if isinstance(rationale, str) and rationale.strip() else ""
