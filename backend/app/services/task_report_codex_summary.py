from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.codex_metrics import primary_metric, selected_model_metrics
from backend.app.services.task_report_formatting import (
    format_metric_value,
)


def codex_result_summary(task: TaskRecord, metrics: dict[str, Any]) -> list[str]:
    selected = selected_model_metrics(metrics)
    metric_name, metric_value = _codex_summary_metric(task, selected, metrics)
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


def _codex_summary_metric(
    task: TaskRecord,
    selected: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[str, float | None]:
    if task.last_run:
        return task.last_run.metric_name, task.last_run.metric_value
    metric_name, metric_value = primary_metric(selected, metrics)
    return (metric_name, metric_value) if metric_value is not None else ("", None)


def _codex_summary_best_model(task: TaskRecord, selected: dict[str, Any]) -> str | None:
    selected_name = selected.get("name")
    if isinstance(selected_name, str):
        return selected_name
    return task.last_run.best_model if task.last_run else None


def _codex_summary_rationale(selected: dict[str, Any]) -> str:
    rationale = selected.get("selection_rationale")
    return rationale.strip() if isinstance(rationale, str) and rationale.strip() else ""
