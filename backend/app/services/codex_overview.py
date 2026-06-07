from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import (
    coerce_float,
    dict_or_empty,
    format_metric,
    list_of_dicts,
    lower_is_better,
    nested_get,
    workspace_path_from_artifacts,
)
from backend.app.services.codex_metrics import selected_model_metrics
from backend.app.services.codex_overview_checks import derive_result_checks
from backend.app.services.codex_overview_factors import derive_key_factors
from backend.app.services.codex_overview_metrics import overview_baseline_metric, overview_primary_metric
from backend.app.services.codex_overview_optimization import derive_optimization_records


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
        "target_columns": _target_columns_from_overview(payload),
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
            "target": _target_text_from_metrics(metrics),
            "target_columns": _target_columns_from_metrics(metrics),
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
        "confidence": _derive_confidence(metric_name, metric_value, baseline_value, diagnostics),
        "target_columns": _target_columns_from_metrics(metrics),
        "target_metrics": _target_metrics_from_metrics(metrics),
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
            "actual_vs_predicted": _sample_actual_vs_predicted(metrics),
            "metric_series": _metric_series(metrics, metric_name),
        },
        "source_files": {
            "metrics": "output/metrics.json",
            "report": "output/report.md",
            "prediction_csv": prediction_csv,
            "feature_importance": feature_importance_path,
        },
    }


def _target_columns_from_overview(payload: dict[str, Any]) -> list[str]:
    summary = payload.get("task_summary") if isinstance(payload.get("task_summary"), dict) else {}
    for value in (payload.get("target_columns"), payload.get("targets"), summary.get("target_columns"), summary.get("targets")):
        targets = _string_list(value)
        if targets:
            return targets
    return []


def _target_columns_from_metrics(metrics: dict[str, Any]) -> list[str]:
    task = metrics.get("task") if isinstance(metrics.get("task"), dict) else {}
    for value in (task.get("target_columns"), task.get("targets"), metrics.get("target_columns"), metrics.get("targets")):
        targets = _string_list(value)
        if targets:
            return targets
    target = task.get("target_column")
    return [str(target)] if isinstance(target, str) and target.strip() else []


def _target_text_from_metrics(metrics: dict[str, Any]) -> str | None:
    targets = _target_columns_from_metrics(metrics)
    if targets:
        return "、".join(targets)
    value = nested_get(metrics, ("task", "target_mode"))
    return str(value) if value else None


def _target_metrics_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    for key in ("target_metrics", "metrics_by_target", "per_target_metrics"):
        value = metrics.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return []


def _derive_confidence(
    metric_name: str | None,
    metric_value: float | None,
    baseline_value: float | None,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[str] = []
    score_parts: list[float] = []
    if metric_name and metric_value is not None:
        if baseline_value is not None and baseline_value != 0:
            if lower_is_better(metric_name):
                improvement = (baseline_value - metric_value) / abs(baseline_value)
            else:
                improvement = (metric_value - baseline_value) / abs(baseline_value)
            score_parts.append(max(0.0, min(1.0, 0.5 + improvement)))
        elif metric_name in {"accuracy", "macro_f1", "r2", "within_relative_error_25pct"}:
            score_parts.append(max(0.0, min(1.0, metric_value)))
    else:
        warnings.append("未找到真实主评估指标，无法评估可信度。")

    leakage = diagnostics.get("leakage") if isinstance(diagnostics.get("leakage"), dict) else {}
    if leakage:
        warnings.append(str(leakage.get("interpretation") or "存在需要复核的切分或泄漏风险。"))
        score_parts.append(0.35)
    if isinstance(diagnostics.get("target_distribution_note"), str):
        warnings.append(diagnostics["target_distribution_note"])
        score_parts.append(0.55)

    if not score_parts:
        return {
            "score": None,
            "level": "unknown",
            "display": "未知",
            "rationale": "当前任务没有足够结构化证据计算可信度。",
            "warnings": warnings,
        }

    score = sum(score_parts) / len(score_parts)
    level = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"
    display = {"high": "高", "medium": "中", "low": "低"}[level]
    return {
        "score": round(score, 3),
        "level": level,
        "display": display,
        "rationale": "可信度根据主指标、baseline 对比和诊断风险综合估计。",
        "warnings": warnings,
    }


def _sample_actual_vs_predicted(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows = metrics.get("top_error_cases")
    if not isinstance(rows, list):
        return []
    points = []
    for index, row in enumerate(rows[:12], start=1):
        if not isinstance(row, dict):
            continue
        actual = coerce_float(row.get("Value") or row.get("actual") or row.get("actual_value"))
        predicted = coerce_float(row.get("predicted_value") or row.get("prediction") or row.get("predicted"))
        if actual is None or predicted is None:
            continue
        points.append({"x": str(row.get("record_id") or index), "actual": actual, "predicted": predicted})
    return points


def _metric_series(metrics: dict[str, Any], metric_name: str | None) -> list[dict[str, Any]]:
    if not metric_name:
        return []
    candidates = metrics.get("candidate_models")
    if isinstance(candidates, dict):
        iterable = candidates.items()
    elif isinstance(candidates, list):
        iterable = ((str(item.get("name") or index), item) for index, item in enumerate(candidates, start=1) if isinstance(item, dict))
    else:
        return []
    series = []
    for name, payload in iterable:
        if not isinstance(payload, dict):
            continue
        value = None
        for split in ("validation", "test", "holdout", "cross_validation"):
            container = payload.get(split)
            if isinstance(container, dict):
                value = coerce_float(container.get(metric_name))
                if value is not None:
                    break
        if value is not None:
            series.append({"label": str(name), "value": value})
    return series[:12]
