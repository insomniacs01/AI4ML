from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.services.codex_common import (
    coerce_float,
    dict_or_empty,
    format_metric,
    list_of_dicts,
    lower_is_better,
    nested_get,
    read_json,
    workspace_path_from_artifacts,
)
from backend.app.services.codex_metrics import primary_metric, selected_model_metrics


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
    metric_name, metric_value, metric_split = _overview_primary_metric(selected, metrics)
    baseline_name, baseline_value = _overview_baseline_metric(metrics, metric_name, metric_split)
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
        "key_factors": _derive_key_factors(metrics),
        "result_checks": _derive_result_checks(metrics, metric_name, metric_value, baseline_name, baseline_value, diagnostics, workspace_path),
        "optimization_records": _derive_optimization_records(metrics, workspace_path, metric_name),
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


def _overview_primary_metric(
    selected: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[str | None, float | None, str | None]:
    for split in ("test", "validation", "cross_validation", "holdout"):
        container = selected.get(split)
        if not isinstance(container, dict):
            continue
        for name in (
            "signed_log_mae",
            "mae",
            "rmse",
            "median_absolute_error",
            "macro_f1",
            "accuracy",
            "r2",
            "within_relative_error_25pct",
        ):
            value = coerce_float(container.get(name))
            if value is not None:
                return name, value, split
    name, value = primary_metric(selected, metrics)
    return (name if value is not None else None), value, None


def _overview_baseline_metric(
    metrics: dict[str, Any],
    metric_name: str | None,
    split: str | None,
) -> tuple[str | None, float | None]:
    if not metric_name:
        return None, None
    baselines = metrics.get("baselines")
    if not isinstance(baselines, dict):
        return None, None
    candidates = _overview_baseline_candidates(baselines, metric_name, split)
    if not candidates:
        return None, None
    if lower_is_better(metric_name):
        return min(candidates, key=lambda item: item[1])
    return max(candidates, key=lambda item: item[1])


def _overview_baseline_candidates(
    baselines: dict[str, Any],
    metric_name: str,
    split: str | None,
) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for name, payload in baselines.items():
        if not isinstance(payload, dict):
            continue
        container = _overview_baseline_container(payload, split)
        if not isinstance(container, dict):
            continue
        value = coerce_float(container.get(metric_name))
        if value is not None:
            candidates.append((str(name), value))
    return candidates


def _overview_baseline_container(payload: dict[str, Any], split: str | None) -> dict[str, Any] | None:
    requested = payload.get(split or "test")
    if isinstance(requested, dict):
        return requested

    for fallback_split in ("test", "validation", "holdout", "cross_validation"):
        candidate = payload.get(fallback_split)
        if isinstance(candidate, dict):
            return candidate
    return None


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


def _derive_result_checks(
    metrics: dict[str, Any],
    metric_name: str | None,
    metric_value: float | None,
    baseline_name: str | None,
    baseline_value: float | None,
    diagnostics: dict[str, Any],
    workspace_path: str | None,
) -> list[dict[str, Any]]:
    checks = [
        _baseline_comparison_check(metric_name, metric_value, baseline_name, baseline_value),
        _validation_split_check(metrics),
        _leakage_check(diagnostics),
        _artifact_consistency_check(workspace_path),
        _prediction_entrypoint_check(metrics),
    ]
    data_quality = _data_quality_check(metrics)
    if data_quality:
        checks.append(data_quality)
    return checks


def _baseline_comparison_check(
    metric_name: str | None,
    metric_value: float | None,
    baseline_name: str | None,
    baseline_value: float | None,
) -> dict[str, Any]:
    has_baseline = bool(baseline_name and baseline_value is not None and metric_value is not None)
    return {
        "name": "baseline_comparison",
        "status": "passed" if has_baseline else "warning",
        "detail": "已找到 baseline 对照。" if baseline_name else "未找到可解析的 baseline 对照。",
        "evidence": f"{baseline_name}: {metric_name} = {format_metric(baseline_value)}" if baseline_name else None,
    }


def _validation_split_check(metrics: dict[str, Any]) -> dict[str, Any]:
    has_split = isinstance(metrics.get("split"), dict)
    return {
        "name": "validation_split",
        "status": "passed" if has_split else "warning",
        "detail": "已记录训练/验证/测试切分。" if has_split else "metrics.json 未记录清晰切分。",
        "evidence": nested_get(metrics, ("split", "strategy")),
    }


def _leakage_check(diagnostics: dict[str, Any]) -> dict[str, Any]:
    has_leakage = isinstance(diagnostics.get("leakage"), dict)
    return {
        "name": "leakage_check",
        "status": "warning" if has_leakage else "not_applicable",
        "detail": str(nested_get(diagnostics, ("leakage", "interpretation")) or "未记录独立泄漏检查。"),
        "evidence": "diagnostics.leakage" if has_leakage else None,
    }


def _artifact_consistency_check(workspace_path: str | None) -> dict[str, Any]:
    return {
        "name": "artifact_consistency",
        "status": "passed" if workspace_path else "warning",
        "detail": "已定位 Codex workspace 和 metrics 产物。" if workspace_path else "未定位 Codex workspace。",
        "evidence": workspace_path,
    }


def _prediction_entrypoint_check(metrics: dict[str, Any]) -> dict[str, Any]:
    entrypoint = nested_get(metrics, ("artifacts", "predict_py")) or nested_get(metrics, ("artifacts", "predict"))
    return {
        "name": "prediction_entrypoint",
        "status": "passed" if entrypoint else "warning",
        "detail": "已记录预测入口。" if entrypoint else "metrics.json 未记录预测入口。",
        "evidence": entrypoint,
    }


def _data_quality_check(metrics: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(metrics.get("dataset"), dict):
        return None
    return {
        "name": "data_quality",
        "status": "passed",
        "detail": "已记录数据规模、缺失处理或分布信息。",
        "evidence": f"rows={nested_get(metrics, ('dataset', 'raw_rows'))}",
    }


def _derive_optimization_records(
    metrics: dict[str, Any],
    workspace_path: str | None,
    metric_name: str | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    diagnostics = metrics.get("diagnostics") if isinstance(metrics.get("diagnostics"), dict) else {}
    diagnostic_record = _diagnostic_optimization_record(diagnostics, metric_name)
    if diagnostic_record:
        records.append(diagnostic_record)
    worker_record = _optimization_worker_record(workspace_path, metric_name)
    if worker_record:
        records.append(worker_record)
    return records


def _diagnostic_optimization_record(
    diagnostics: dict[str, Any],
    metric_name: str | None,
) -> dict[str, Any] | None:
    summary = diagnostics.get("bounded_optimization_summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    detail = summary.strip()
    return {
        "name": "bounded_optimization",
        "change": detail,
        "before_metric": None,
        "after_metric": None,
        "metric_name": metric_name,
        "result": "not_comparable",
        "detail": detail,
    }


def _optimization_worker_record(workspace_path: str | None, metric_name: str | None) -> dict[str, Any] | None:
    if not workspace_path:
        return None
    payload = read_json(
        Path(workspace_path) / "work" / "subagents" / "optimization_worker" / "optimization_results.json"
    )
    if not isinstance(payload, dict):
        return None
    reference = (
        payload.get("parent_first_round_reference")
        if isinstance(payload.get("parent_first_round_reference"), dict)
        else {}
    )
    best = payload.get("best_candidate") if isinstance(payload.get("best_candidate"), dict) else {}
    before_value, after_value = _optimization_metric_values(reference, best, metric_name)
    return {
        "name": str(best.get("candidate") or best.get("route") or "optimization_worker"),
        "change": str(best.get("route") or "optimization_worker 选择的最佳候选路线"),
        "before_metric": before_value,
        "after_metric": after_value,
        "metric_name": metric_name,
        "result": _optimization_result(metric_name, before_value, after_value),
        "detail": f"optimization_worker 评估了 {len(payload.get('candidate_results') or [])} 个候选配置。",
    }


def _optimization_metric_values(
    reference: dict[str, Any],
    best: dict[str, Any],
    metric_name: str | None,
) -> tuple[float | None, float | None]:
    if not metric_name:
        return None, None
    best_metrics = nested_get(best, ("metrics", "validation"))
    before_value = coerce_float(reference.get(f"validation_{metric_name}"))
    after_value = coerce_float(best_metrics.get(metric_name)) if isinstance(best_metrics, dict) else None
    return before_value, after_value


def _optimization_result(
    metric_name: str | None,
    before_value: float | None,
    after_value: float | None,
) -> str:
    if before_value is None or after_value is None or not metric_name:
        return "not_comparable"
    if lower_is_better(metric_name):
        return "improved" if after_value < before_value else "worse" if after_value > before_value else "no_change"
    return "improved" if after_value > before_value else "worse" if after_value < before_value else "no_change"


def _derive_key_factors(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    selected = metrics.get("selected_model") if isinstance(metrics.get("selected_model"), dict) else {}
    factors = _feature_importance_factors(selected.get("feature_importance"))
    if factors:
        return factors
    return _error_analysis_factors(metrics)


def _feature_importance_factors(raw_importance: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_importance, dict):
        return []
    factors: list[dict[str, Any]] = []
    items = sorted(raw_importance.items(), key=lambda item: abs(coerce_float(item[1]) or 0), reverse=True)
    for name, value in items[:8]:
        numeric = coerce_float(value)
        if not isinstance(name, str) or numeric is None:
            continue
        factors.append(
            {
                "name": name,
                "importance": numeric,
                "display": name,
                "source": "model_feature_importance",
                "is_model_feature_importance": True,
                "direction": _factor_direction(numeric),
                "evidence": "来自 metrics.json selected_model.feature_importance。",
            }
        )
    return factors


def _factor_direction(value: float) -> str:
    return "positive" if value > 0 else "negative" if value < 0 else "unknown"


def _error_analysis_factors(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    error_analysis = metrics.get("error_analysis") if isinstance(metrics.get("error_analysis"), dict) else {}
    source_rows = error_analysis.get("by_source_category_test")
    factors: list[dict[str, Any]] = []
    if isinstance(source_rows, list):
        sorted_rows = sorted(
            [row for row in source_rows if isinstance(row, dict)],
            key=lambda row: coerce_float(row.get("signed_log_mae")) or -1,
            reverse=True,
        )
        for row in sorted_rows[:5]:
            name = row.get("Source_Category")
            value = coerce_float(row.get("signed_log_mae"))
            if not name or value is None:
                continue
            factors.append(
                {
                    "name": str(name),
                    "importance": value,
                    "display": str(name),
                    "source": "error_analysis",
                    "is_model_feature_importance": False,
                    "direction": "unknown",
                    "evidence": f"测试集该来源分组 signed_log_mae = {format_metric(value)}，表示该分组误差较高。",
                }
            )
    return factors


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
