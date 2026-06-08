from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_report_formatting import (
    coerce_float as _coerce_float,
    escape_table_cell as _escape_table_cell,
    format_integer as _format_integer,
    format_metric_value as _format_metric_value,
    format_percent as _format_percent,
    normalize_report_metric as _normalize_report_metric,
    status_label as _status_label,
)


REPORT_LOWER_IS_BETTER_METRICS = {
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


def baseline_experiment_lines(agent_loop: dict[str, Any], task: TaskRecord) -> list[str]:
    baseline = agent_loop.get("baseline") if isinstance(agent_loop, dict) else None
    if not isinstance(baseline, dict):
        return ["- 尚未记录简单对照，无法和正式模型做最低参考线对比。"]
    if baseline.get("status") != "completed":
        return [f"- 简单对照状态：{_status_label(baseline.get('status'))}。{baseline.get('detail') or '尚无细节。'}"]

    lines = _baseline_summary_lines(baseline, task)
    lines.extend(_baseline_distribution_lines(baseline))
    lines.extend(_baseline_note_lines(baseline))
    lines.extend(_baseline_comparison_lines(task, baseline))
    return lines


def _baseline_summary_lines(baseline: dict[str, Any], task: TaskRecord) -> list[str]:
    lines = [
        "简单对照的作用是先用最简单、可解释的方法建立最低参考线，确认自动模型确实学到了超过常数预测或多数类预测的信息。",
        "",
        "| 项目 | 数值 |",
        "| --- | --- |",
        f"| 方法 | {_escape_table_cell(baseline.get('label') or baseline.get('method') or '简单对照')} |",
        f"| 问题类型 | {_escape_table_cell(baseline.get('problem_type') or task.problem_type or '未记录')} |",
        f"| 目标列 | {_escape_table_cell(baseline.get('target_column') or task.label_column or '未记录')} |",
        f"| 训练样本数 | {_format_integer(baseline.get('train_count'))} |",
        f"| 验证样本数 | {_format_integer(baseline.get('validation_count'))} |",
        f"| 评价指标 | {_escape_table_cell(baseline.get('metric_name') or 'metric')} |",
        f"| 指标数值 | {_format_metric_value(baseline.get('metric_value'))} |",
    ]
    if baseline.get("prediction_value") is not None:
        lines.append(f"| 常数预测值 | {_format_metric_value(baseline.get('prediction_value'))} |")
    if baseline.get("majority_label") is not None:
        lines.append(f"| 多数类 | {_escape_table_cell(baseline.get('majority_label'))} |")
        lines.append(f"| 多数类训练占比 | {_format_percent(baseline.get('majority_ratio'))} |")
    return lines


def _baseline_distribution_lines(baseline: dict[str, Any]) -> list[str]:
    distribution = baseline.get("class_distribution")
    if not isinstance(distribution, dict) or not distribution:
        return []
    lines = ["", "多数类简单对照的训练集类别分布如下。", "", "| 类别 | 数量 |", "| --- | ---: |"]
    for label, count in list(distribution.items())[:10]:
        lines.append(f"| {_escape_table_cell(label)} | {_format_integer(count)} |")
    return lines


def _baseline_note_lines(baseline: dict[str, Any]) -> list[str]:
    notes = baseline.get("notes")
    if not isinstance(notes, list) or not notes:
        return []
    return ["", "简单对照说明：", *[f"- {item}" for item in notes if isinstance(item, str)]]


def _baseline_comparison_lines(task: TaskRecord, baseline: dict[str, Any]) -> list[str]:
    comparison = compare_task_to_baseline(task, baseline)
    if comparison:
        return ["", f"正式模型对比：{comparison_sentence(comparison)}"]
    if task.last_run:
        return ["", "- 正式模型与简单对照的指标口径不一致或简单对照不完整，暂不能直接比较。"]
    return []


def compare_task_to_baseline(task: TaskRecord, baseline: Any) -> dict[str, Any] | None:
    if not task.last_run or not isinstance(baseline, dict) or baseline.get("status") != "completed":
        return None
    model_metric = _normalize_report_metric(task.last_run.metric_name)
    baseline_metric = _normalize_report_metric(str(baseline.get("metric_name") or ""))
    if model_metric != baseline_metric:
        return None
    baseline_value = _coerce_float(baseline.get("metric_value"))
    model_value = _coerce_float(task.last_run.metric_value)
    if baseline_value is None or model_value is None:
        return None
    lower_better = model_metric in REPORT_LOWER_IS_BETTER_METRICS
    delta = baseline_value - model_value if lower_better else model_value - baseline_value
    denominator = abs(baseline_value) if abs(baseline_value) > 1e-12 else 1.0
    return {
        "metric_name": task.last_run.metric_name,
        "model_value": model_value,
        "baseline_value": baseline_value,
        "delta": delta,
        "relative_delta": delta / denominator,
        "better": delta > 0,
        "direction": "lower" if lower_better else "higher",
    }


def comparison_sentence(comparison: dict[str, Any]) -> str:
    direction = "降低" if comparison.get("direction") == "lower" else "提高"
    if not comparison.get("better"):
        direction = "未改善"
    return (
        f"模型 {comparison.get('metric_name')} = {_format_metric_value(comparison.get('model_value'))}，"
        f"简单对照 = {_format_metric_value(comparison.get('baseline_value'))}，"
        f"相对简单对照{direction} {_format_percent(abs(comparison.get('relative_delta') or 0))}"
    )
