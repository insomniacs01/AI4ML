from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import format_metric, nested_get


def derive_result_checks(
    metrics: dict[str, Any],
    metric_name: str | None,
    metric_value: float | None,
    baseline_name: str | None,
    baseline_value: float | None,
    diagnostics: dict[str, Any],
    workspace_path: str | None,
) -> list[dict[str, Any]]:
    checks = [
        baseline_comparison_check(metric_name, metric_value, baseline_name, baseline_value),
        validation_split_check(metrics),
        leakage_check(diagnostics),
        artifact_consistency_check(workspace_path),
        prediction_entrypoint_check(metrics),
    ]
    data_quality = data_quality_check(metrics)
    if data_quality:
        checks.append(data_quality)
    return checks


def baseline_comparison_check(
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


def validation_split_check(metrics: dict[str, Any]) -> dict[str, Any]:
    has_split = isinstance(metrics.get("split"), dict)
    return {
        "name": "validation_split",
        "status": "passed" if has_split else "warning",
        "detail": "已记录训练/验证/测试切分。" if has_split else "metrics.json 未记录清晰切分。",
        "evidence": nested_get(metrics, ("split", "strategy")),
    }


def leakage_check(diagnostics: dict[str, Any]) -> dict[str, Any]:
    has_leakage = isinstance(diagnostics.get("leakage"), dict)
    return {
        "name": "leakage_check",
        "status": "warning" if has_leakage else "not_applicable",
        "detail": str(nested_get(diagnostics, ("leakage", "interpretation")) or "未记录独立泄漏检查。"),
        "evidence": "diagnostics.leakage" if has_leakage else None,
    }


def artifact_consistency_check(workspace_path: str | None) -> dict[str, Any]:
    return {
        "name": "artifact_consistency",
        "status": "passed" if workspace_path else "warning",
        "detail": "已定位 Codex workspace 和 metrics 产物。" if workspace_path else "未定位 Codex workspace。",
        "evidence": workspace_path,
    }


def prediction_entrypoint_check(metrics: dict[str, Any]) -> dict[str, Any]:
    entrypoint = nested_get(metrics, ("artifacts", "predict_py")) or nested_get(metrics, ("artifacts", "predict"))
    return {
        "name": "prediction_entrypoint",
        "status": "passed" if entrypoint else "warning",
        "detail": "已记录预测入口。" if entrypoint else "metrics.json 未记录预测入口。",
        "evidence": entrypoint,
    }


def data_quality_check(metrics: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(metrics.get("dataset"), dict):
        return None
    return {
        "name": "data_quality",
        "status": "passed",
        "detail": "已记录数据规模、缺失处理或分布信息。",
        "evidence": f"rows={nested_get(metrics, ('dataset', 'raw_rows'))}",
    }
