from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.services.codex_common import coerce_float, lower_is_better, nested_get, read_json


def derive_optimization_records(
    metrics: dict[str, Any],
    workspace_path: str | None,
    metric_name: str | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    diagnostics = metrics.get("diagnostics") if isinstance(metrics.get("diagnostics"), dict) else {}
    diagnostic_record = diagnostic_optimization_record(diagnostics, metric_name)
    if diagnostic_record:
        records.append(diagnostic_record)
    worker_record = optimization_worker_record(workspace_path, metric_name)
    if worker_record:
        records.append(worker_record)
    return records


def diagnostic_optimization_record(
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


def optimization_worker_record(workspace_path: str | None, metric_name: str | None) -> dict[str, Any] | None:
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
    before_value, after_value = optimization_metric_values(reference, best, metric_name)
    return {
        "name": str(best.get("candidate") or best.get("route") or "optimization_worker"),
        "change": str(best.get("route") or "optimization_worker 选择的最佳候选路线"),
        "before_metric": before_value,
        "after_metric": after_value,
        "metric_name": metric_name,
        "result": optimization_result(metric_name, before_value, after_value),
        "detail": f"optimization_worker 评估了 {len(payload.get('candidate_results') or [])} 个候选配置。",
    }


def optimization_metric_values(
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


def optimization_result(
    metric_name: str | None,
    before_value: float | None,
    after_value: float | None,
) -> str:
    if before_value is None or after_value is None or not metric_name:
        return "not_comparable"
    if lower_is_better(metric_name):
        return "improved" if after_value < before_value else "worse" if after_value > before_value else "no_change"
    return "improved" if after_value > before_value else "worse" if after_value < before_value else "no_change"
