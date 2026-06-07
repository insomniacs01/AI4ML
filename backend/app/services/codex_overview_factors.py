from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import coerce_float, format_metric


def derive_key_factors(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    selected = metrics.get("selected_model") if isinstance(metrics.get("selected_model"), dict) else {}
    factors = feature_importance_factors(selected.get("feature_importance"))
    if factors:
        return factors
    return error_analysis_factors(metrics)


def feature_importance_factors(raw_importance: Any) -> list[dict[str, Any]]:
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
                "direction": factor_direction(numeric),
                "evidence": "来自 metrics.json selected_model.feature_importance。",
            }
        )
    return factors


def factor_direction(value: float) -> str:
    return "positive" if value > 0 else "negative" if value < 0 else "unknown"


def error_analysis_factors(metrics: dict[str, Any]) -> list[dict[str, Any]]:
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
