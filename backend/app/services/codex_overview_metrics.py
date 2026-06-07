from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import coerce_float, lower_is_better
from backend.app.services.codex_metrics import primary_metric


PREFERRED_OVERVIEW_METRICS = (
    "signed_log_mae",
    "mae",
    "rmse",
    "median_absolute_error",
    "macro_f1",
    "accuracy",
    "r2",
    "within_relative_error_25pct",
)

PREFERRED_OVERVIEW_SPLITS = ("test", "validation", "cross_validation", "holdout")


def overview_primary_metric(
    selected: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[str | None, float | None, str | None]:
    for split in PREFERRED_OVERVIEW_SPLITS:
        container = selected.get(split)
        if not isinstance(container, dict):
            continue
        for name in PREFERRED_OVERVIEW_METRICS:
            value = coerce_float(container.get(name))
            if value is not None:
                return name, value, split
    name, value = primary_metric(selected, metrics)
    return (name if value is not None else None), value, None


def overview_baseline_metric(
    metrics: dict[str, Any],
    metric_name: str | None,
    split: str | None,
) -> tuple[str | None, float | None]:
    if not metric_name:
        return None, None
    baselines = metrics.get("baselines")
    if not isinstance(baselines, dict):
        return None, None
    candidates = overview_baseline_candidates(baselines, metric_name, split)
    if not candidates:
        return None, None
    if lower_is_better(metric_name):
        return min(candidates, key=lambda item: item[1])
    return max(candidates, key=lambda item: item[1])


def overview_baseline_candidates(
    baselines: dict[str, Any],
    metric_name: str,
    split: str | None,
) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for name, payload in baselines.items():
        if not isinstance(payload, dict):
            continue
        container = overview_baseline_container(payload, split)
        if not isinstance(container, dict):
            continue
        value = coerce_float(container.get(metric_name))
        if value is not None:
            candidates.append((str(name), value))
    return candidates


def overview_baseline_container(payload: dict[str, Any], split: str | None) -> dict[str, Any] | None:
    requested = payload.get(split or "test")
    if isinstance(requested, dict):
        return requested

    for fallback_split in PREFERRED_OVERVIEW_SPLITS:
        candidate = payload.get(fallback_split)
        if isinstance(candidate, dict):
            return candidate
    return None
