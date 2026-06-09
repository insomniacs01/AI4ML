from __future__ import annotations

from typing import Any

from backend.app.models.task import RunSummary, TaskRunProgressLeaderboardRow
from backend.app.services.codex_common import coerce_float
from backend.app.services.codex_usage import read_codex_token_usage


def build_codex_run_summary(workspace_path: str | None, metrics: dict[str, Any]) -> RunSummary | None:
    if not workspace_path:
        return None
    selected = selected_model_metrics(metrics)
    metric_name, metric_value = primary_metric(selected, metrics)
    if metric_value is None:
        return None
    leaderboard = [row.model_dump(mode="json") for row in leaderboard_from_metrics(metrics)]
    return RunSummary(
        best_model=str(selected.get("name") or metrics.get("best_model") or "codex_model"),
        metric_name=metric_name,
        metric_value=metric_value,
        validation_score=metric_value,
        leaderboard=leaderboard,
        output_dir=workspace_path,
        token_usage=read_codex_token_usage(workspace_path),
    )


def leaderboard_from_metrics(metrics: dict[str, Any]) -> list[TaskRunProgressLeaderboardRow]:
    candidates = metrics.get("candidate_models")
    if isinstance(candidates, dict):
        candidate_items = [
            {"name": name, **payload}
            for name, payload in candidates.items()
            if isinstance(payload, dict)
        ]
    elif isinstance(candidates, list):
        candidate_items = candidates
    elif isinstance(metrics.get("models"), dict):
        candidate_items = [
            {"name": name, **payload}
            for name, payload in metrics["models"].items()
            if isinstance(payload, dict)
        ]
    else:
        return []
    rows: list[TaskRunProgressLeaderboardRow] = []
    for index, item in enumerate(candidate_items, start=1):
        if not isinstance(item, dict):
            continue
        _metric_name, metric_value = primary_metric(item, metrics)
        rows.append(
            TaskRunProgressLeaderboardRow(
                model=str(item.get("name") or item.get("type") or f"candidate_{index}"),
                validation_score=metric_value,
                rank=index,
            )
        )
    return rows


def selected_model_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    selected = metrics.get("selected_model") if isinstance(metrics.get("selected_model"), dict) else {}
    if selected:
        return selected
    final_model = metrics.get("final_model") if isinstance(metrics.get("final_model"), dict) else {}
    if final_model:
        model_name = str(final_model.get("name") or "").strip()
        candidates = metrics.get("candidate_models") if isinstance(metrics.get("candidate_models"), dict) else {}
        candidate = candidates.get(model_name) if model_name and isinstance(candidates.get(model_name), dict) else {}
        return {"name": model_name, **candidate, **final_model} if model_name else final_model
    best = metrics.get("best_model") if isinstance(metrics.get("best_model"), dict) else {}
    if best:
        return best
    selected_name = str(metrics.get("selected_model_name") or metrics.get("best_model_name") or "").strip()
    models = metrics.get("models") if isinstance(metrics.get("models"), dict) else {}
    if selected_name and isinstance(models.get(selected_name), dict):
        return {"name": selected_name, **models[selected_name]}
    return {}


def primary_metric(model_payload: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, float | None]:
    metric_name, metric_value = _flat_primary_metric(model_payload, metrics)
    if metric_value is not None:
        return metric_name, metric_value
    for container_name in ("test", "validation", "cross_validation", "holdout"):
        container = model_payload.get(container_name)
        if not isinstance(container, dict):
            continue
        for metric_name in (
            "selection_metric_value",
            "signed_log_mae",
            "signed_log_rmse",
            "median_absolute_error",
            "macro_f1_mean",
            "accuracy_mean",
            "macro_f1",
            "accuracy",
            "r2",
            "rmse",
            "mae",
        ):
            value = coerce_float(container.get(metric_name))
            if value is not None:
                return metric_name, value
    validation = metrics.get("validation") if isinstance(metrics.get("validation"), dict) else {}
    for metric_name in (
        "metric_value",
        "score",
        "signed_log_mae",
        "signed_log_rmse",
        "median_absolute_error",
        "accuracy",
        "macro_f1",
        "r2",
        "rmse",
        "mae",
    ):
        value = coerce_float(validation.get(metric_name) or metrics.get(metric_name))
        if value is not None:
            return metric_name, value
    return "metric", None


def _flat_primary_metric(model_payload: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, float | None]:
    selected_metric = str(
        model_payload.get("selection_metric")
        or metrics.get("selection_metric")
        or metrics.get("primary_metric")
        or ""
    ).strip()
    metric_names = [
        selected_metric,
        "selection_metric_value",
        "signed_log_mae",
        "signed_log_rmse",
        "median_absolute_error",
        "macro_f1_mean",
        "accuracy_mean",
        "macro_f1",
        "accuracy",
        "r2",
        "rmse",
        "mae",
    ]
    metric_names = [name for index, name in enumerate(metric_names) if name and name not in metric_names[:index]]
    for container in (model_payload, metrics):
        for metric_name in metric_names:
            value = coerce_float(container.get(metric_name))
            if value is not None:
                return _display_metric_name(metric_name, selected_metric), value
            for prefix in ("validation", "test", "holdout", "cross_validation"):
                value = coerce_float(container.get(f"{prefix}_{metric_name}"))
                if value is not None:
                    return _display_metric_name(metric_name, selected_metric), value
    return "metric", None


def _display_metric_name(metric_name: str, selected_metric: str) -> str:
    if metric_name == "selection_metric_value" and selected_metric:
        return selected_metric
    return metric_name
