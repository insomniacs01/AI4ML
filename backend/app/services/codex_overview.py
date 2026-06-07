from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import (
    dict_or_empty,
    format_metric,
    list_of_dicts,
    lower_is_better,
    nested_get,
    workspace_path_from_artifacts,
)
from backend.app.services.codex_metrics import selected_model_metrics
from backend.app.services.codex_overview_charts import actual_vs_predicted_points, metric_series
from backend.app.services.codex_overview_checks import derive_result_checks
from backend.app.services.codex_overview_confidence import derive_confidence
from backend.app.services.codex_overview_factors import derive_key_factors
from backend.app.services.codex_overview_metrics import overview_baseline_metric, overview_primary_metric
from backend.app.services.codex_overview_optimization import derive_optimization_records
from backend.app.services.codex_overview_targets import (
    metrics_target_columns,
    metrics_target_metrics,
    metrics_target_text,
    overview_target_columns,
)


def build_codex_overview_from_artifacts(artifacts: dict[str, Any]) -> dict[str, Any]:
    overview = artifacts.get("overview")
    if isinstance(overview, dict) and overview:
        return _normalize_overview_payload(overview)

    metrics = artifacts.get("metrics") if isinstance(artifacts.get("metrics"), dict) else {}
    if not metrics:
        return {}
    workspace_path = workspace_path_from_artifacts(artifacts)
    return _derive_overview_from_metrics(metrics, workspace_path)


def _normalize_overview_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": str(payload.get("schema_version") or "1.0"),
        "generated_at": payload.get("generated_at"),
        "status": payload.get("status"),
        "task_summary": dict_or_empty(payload.get("task_summary")),
        "prediction_error": dict_or_empty(payload.get("prediction_error")),
        "confidence": dict_or_empty(payload.get("confidence")),
        "target_columns": overview_target_columns(payload),
        "target_metrics": dict_or_empty(payload.get("target_metrics") or payload.get("metrics_by_target")),
        "key_factors": list_of_dicts(payload.get("key_factors")),
        "result_checks": list_of_dicts(payload.get("result_checks")),
        "optimization_records": list_of_dicts(payload.get("optimization_records")),
        "charts": dict_or_empty(payload.get("charts")),
        "source_files": dict_or_empty(payload.get("source_files")),
    }


def _derive_overview_from_metrics(metrics: dict[str, Any], workspace_path: str | None) -> dict[str, Any]:
    selected = selected_model_metrics(metrics)
    metric_name, metric_value, metric_split = overview_primary_metric(selected, metrics)
    baseline_name, baseline_value = overview_baseline_metric(metrics, metric_name, metric_split)
    diagnostics = metrics.get("diagnostics") if isinstance(metrics.get("diagnostics"), dict) else {}
    prediction_csv = nested_get(metrics, ("artifacts", "prediction_csv"))
    feature_importance_path = nested_get(metrics, ("artifacts", "feature_importance"))
    target_columns = metrics_target_columns(metrics)

    if metric_name and metric_value is not None:
        error_interpretation = f"{metric_split or '评估集'} 上的主指标为 {metric_name} = {format_metric(metric_value)}。"
    elif metric_name:
        error_interpretation = f"已识别主指标 {metric_name}，但没有可用数值。"
    else:
        error_interpretation = "当前 metrics.json 未提供可识别的主评估指标。"

    return {
        "schema_version": "1.0",
        "generated_at": metrics.get("created_at"),
        "status": "completed",
        "task_summary": {
            "title": "Codex 建模结果",
            "target": metrics_target_text(metrics, target_columns),
            "target_columns": target_columns,
            "task_type": nested_get(metrics, ("task", "target_mode")) or "other",
            "conclusion": "已生成结构化建模结果；请结合误差、可信度和报告说明使用。",
            "recommendation": "先查看报告和结果检查，再决定是否用于业务决策。",
        },
        "prediction_error": {
            "primary_metric": metric_name,
            "value": metric_value,
            "display": f"{metric_name} = {format_metric(metric_value)}" if metric_name and metric_value is not None else None,
            "split": metric_split,
            "lower_is_better": lower_is_better(metric_name),
            "baseline_metric": baseline_value,
            "baseline_name": baseline_name,
            "interpretation": error_interpretation,
        },
        "confidence": derive_confidence(metric_name, metric_value, baseline_value, diagnostics),
        "target_columns": target_columns,
        "target_metrics": metrics_target_metrics(metrics),
        "key_factors": derive_key_factors(metrics),
        "result_checks": derive_result_checks(
            metrics,
            metric_name,
            metric_value,
            baseline_name,
            baseline_value,
            diagnostics,
            workspace_path,
        ),
        "optimization_records": derive_optimization_records(metrics, workspace_path, metric_name),
        "charts": {
            "actual_vs_predicted": actual_vs_predicted_points(metrics),
            "metric_series": metric_series(metrics, metric_name),
        },
        "source_files": {
            "metrics": "output/metrics.json",
            "report": "output/report.md",
            "prediction_csv": prediction_csv,
            "feature_importance": feature_importance_path,
        },
    }
