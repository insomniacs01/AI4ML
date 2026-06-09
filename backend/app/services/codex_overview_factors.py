from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import coerce_float, format_metric
from backend.app.services.codex_metrics import selected_model_metrics


def derive_key_factors(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    selected = selected_model_metrics(metrics)
    for raw_importance, source_label in (
        (selected.get("feature_importance"), "selected_model.feature_importance"),
        (metrics.get("feature_importance"), "feature_importance"),
        (metrics.get("features"), "features"),
    ):
        factors = feature_importance_factors(raw_importance, source_label=source_label)
        if factors:
            return factors
    return error_analysis_factors(metrics)


def feature_importance_factors(raw_importance: Any, *, source_label: str = "selected_model.feature_importance") -> list[dict[str, Any]]:
    factors: list[dict[str, Any]] = []
    items = sorted(_feature_importance_items(raw_importance), key=lambda item: abs(item[1]), reverse=True)
    for name, value in items[:8]:
        if not isinstance(name, str):
            continue
        factors.append(
            {
                "name": name,
                "importance": value,
                "display": name,
                "source": "model_feature_importance",
                "is_model_feature_importance": True,
                "direction": factor_direction(value),
                "evidence": f"来自 metrics.json {source_label}。",
            }
        )
    return factors


def _feature_importance_items(raw_importance: Any) -> list[tuple[str, float]]:
    if isinstance(raw_importance, dict):
        if isinstance(raw_importance.get("feature_importance"), (dict, list)):
            return _feature_importance_items(raw_importance["feature_importance"])
        if isinstance(raw_importance.get("features"), (dict, list)):
            return _feature_importance_items(raw_importance["features"])
        rows = [{"feature": key, "importance": value} for key, value in raw_importance.items()]
    elif isinstance(raw_importance, list):
        rows = raw_importance
    else:
        return []

    items: list[tuple[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("feature") or row.get("feature_name") or row.get("name") or row.get("column")
        value = coerce_float(row.get("importance") or row.get("score") or row.get("value"))
        if isinstance(name, str) and name.strip() and value is not None:
            items.append((name.strip(), value))
    return items


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
