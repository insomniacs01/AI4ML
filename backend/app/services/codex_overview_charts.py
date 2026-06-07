from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import coerce_float


def actual_vs_predicted_points(metrics: dict[str, Any]) -> list[dict[str, Any]]:
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


def metric_series(metrics: dict[str, Any], metric_name: str | None) -> list[dict[str, Any]]:
    if not metric_name:
        return []
    candidates = metrics.get("candidate_models")
    if isinstance(candidates, dict):
        iterable = candidates.items()
    elif isinstance(candidates, list):
        iterable = (
            (str(item.get("name") or index), item)
            for index, item in enumerate(candidates, start=1)
            if isinstance(item, dict)
        )
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
