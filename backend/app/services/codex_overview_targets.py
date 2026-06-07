from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import nested_get


def overview_target_columns(payload: dict[str, Any]) -> list[str]:
    summary = payload.get("task_summary") if isinstance(payload.get("task_summary"), dict) else {}
    for value in (payload.get("target_columns"), payload.get("targets"), summary.get("target_columns"), summary.get("targets")):
        targets = string_list(value)
        if targets:
            return targets
    return []


def metrics_target_columns(metrics: dict[str, Any]) -> list[str]:
    task = metrics.get("task") if isinstance(metrics.get("task"), dict) else {}
    for value in (task.get("target_columns"), task.get("targets"), metrics.get("target_columns"), metrics.get("targets")):
        targets = string_list(value)
        if targets:
            return targets
    target = task.get("target_column")
    return [str(target)] if isinstance(target, str) and target.strip() else []


def metrics_target_text(metrics: dict[str, Any], target_columns: list[str] | None = None) -> str | None:
    targets = target_columns if target_columns is not None else metrics_target_columns(metrics)
    if targets:
        return "、".join(targets)
    value = nested_get(metrics, ("task", "target_mode"))
    return str(value) if value else None


def metrics_target_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    for key in ("target_metrics", "metrics_by_target", "per_target_metrics"):
        value = metrics.get(key)
        if isinstance(value, dict):
            return value
    return {}


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return []
