from __future__ import annotations

from typing import Any

from backend.app.models.task import RunSummary, TaskRunProgressLeaderboardRow
from backend.app.services.codex_common import coerce_float
from backend.app.services.codex_usage import read_codex_token_usage


def build_codex_run_summary(
    workspace_path: str | None,
    metrics: dict[str, Any],
    *,
    overview: dict[str, Any] | None = None,
) -> RunSummary | None:
    if not workspace_path:
        return None
    selected = selected_model_metrics(metrics)
    metric_name, metric_value = primary_metric(selected, metrics)
    if metric_value is None:
        metric_name, metric_value = primary_metric_from_overview(overview)
    if metric_value is None:
        return None
    leaderboard = [row.model_dump(mode="json") for row in leaderboard_from_metrics(metrics)]
    return RunSummary(
        best_model=_best_model_name(selected, metrics),
        metric_name=metric_name,
        metric_value=metric_value,
        validation_score=metric_value,
        leaderboard=leaderboard,
        output_dir=workspace_path,
        token_usage=read_codex_token_usage(workspace_path),
    )


def leaderboard_from_metrics(metrics: dict[str, Any]) -> list[TaskRunProgressLeaderboardRow]:
    candidate_items = candidate_model_items(metrics)
    if not candidate_items:
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
    final_model = metrics.get("final_model")
    if isinstance(final_model, dict):
        model_name = str(final_model.get("name") or "").strip()
        candidate = _candidate_by_name(metrics, model_name)
        return {"name": model_name, **candidate, **final_model} if model_name else final_model
    if isinstance(final_model, str) and final_model.strip():
        model_name = final_model.strip()
        candidate = _candidate_by_name(metrics, model_name)
        return {"name": model_name, **candidate}
    best = metrics.get("best_model") if isinstance(metrics.get("best_model"), dict) else {}
    if best:
        return best
    best_model = metrics.get("best_model")
    if isinstance(best_model, str) and best_model.strip():
        model_name = best_model.strip()
        candidate = _candidate_by_name(metrics, model_name)
        return {"name": model_name, **candidate}
    selected_name = str(
        metrics.get("selected_model_name")
        or metrics.get("best_model_name")
        or metrics.get("model_name")
        or ""
    ).strip()
    if selected_name:
        candidate = _candidate_by_name(metrics, selected_name)
        if candidate:
            return {"name": selected_name, **candidate}
    return {}


def primary_metric(model_payload: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, float | None]:
    metric_name, metric_value = _flat_primary_metric(model_payload, metrics)
    if metric_value is not None:
        return metric_name, metric_value
    for container_name in (
        "test",
        "test_metrics",
        "validation",
        "validation_metrics",
        "metrics",
        "cross_validation",
        "holdout",
        "holdout_metrics",
    ):
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
            value = _metric_value(container, metric_name)
            if value is not None:
                return _display_metric_name(metric_name, _selected_metric_name(model_payload, metrics)), value
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
        value = _metric_value(validation, metric_name)
        if value is None:
            value = _metric_value(metrics, metric_name)
        if value is not None:
            return metric_name, value
    return "metric", None


def primary_metric_from_overview(overview: dict[str, Any] | None) -> tuple[str, float | None]:
    if not isinstance(overview, dict):
        return "metric", None
    prediction_error = overview.get("prediction_error")
    if not isinstance(prediction_error, dict):
        return "metric", None
    metric_name = str(
        prediction_error.get("primary_metric")
        or prediction_error.get("metric_name")
        or "metric"
    ).strip() or "metric"
    metric_value = _metric_value(prediction_error, "value")
    if metric_value is None:
        metric_value = _metric_value(prediction_error, "metric_value")
    return metric_name, metric_value


def candidate_model_items(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("candidate_models", "candidates", "models"):
        value = metrics.get(key)
        if isinstance(value, dict):
            return [
                {"name": name, **payload}
                for name, payload in value.items()
                if isinstance(payload, dict)
            ]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _flat_primary_metric(model_payload: dict[str, Any], metrics: dict[str, Any]) -> tuple[str, float | None]:
    selected_metric = _selected_metric_name(model_payload, metrics)
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
    containers = [
        model_payload,
        _dict_value(model_payload, "metrics"),
        _dict_value(model_payload, "validation_metrics"),
        _dict_value(model_payload, "test_metrics"),
        _dict_value(model_payload, "holdout_metrics"),
        metrics,
        _dict_value(metrics, "metrics"),
        _dict_value(metrics, "validation_metrics"),
    ]
    for container in containers:
        for metric_name in metric_names:
            value = _metric_value(container, metric_name)
            if value is not None:
                return _display_metric_name(metric_name, selected_metric), value
            for prefix in ("validation", "test", "holdout", "cross_validation"):
                value = _metric_value(container, f"{prefix}_{metric_name}")
                if value is not None:
                    return _display_metric_name(metric_name, selected_metric), value
    return "metric", None


def _display_metric_name(metric_name: str, selected_metric: str) -> str:
    if metric_name == "selection_metric_value" and selected_metric:
        return selected_metric
    return metric_name


def _selected_metric_name(model_payload: dict[str, Any], metrics: dict[str, Any]) -> str:
    return str(
        model_payload.get("selection_metric")
        or model_payload.get("primary_metric")
        or metrics.get("selection_metric")
        or metrics.get("primary_metric")
        or ""
    ).strip()


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _metric_value(container: dict[str, Any], metric_name: str) -> float | None:
    if not isinstance(container, dict) or not metric_name:
        return None
    candidates = [
        metric_name,
        metric_name.lower(),
        metric_name.upper(),
        metric_name.capitalize(),
    ]
    casefold_map = {str(key).casefold(): key for key in container}
    for name in candidates:
        key = name if name in container else casefold_map.get(name.casefold())
        if key is None:
            continue
        value = container.get(key)
        if isinstance(value, dict):
            for nested_key in ("value", "mean", "score", "metric_value"):
                nested_value = coerce_float(value.get(nested_key))
                if nested_value is not None:
                    return nested_value
            continue
        metric_value = coerce_float(value)
        if metric_value is not None:
            return metric_value
    return None


def _candidate_by_name(metrics: dict[str, Any], model_name: str) -> dict[str, Any]:
    if not model_name:
        return {}
    for item in candidate_model_items(metrics):
        item_name = str(item.get("name") or item.get("type") or "").strip()
        if item_name == model_name:
            return item
    return {}


def _best_model_name(selected: dict[str, Any], metrics: dict[str, Any]) -> str:
    selected_name = str(selected.get("name") or "").strip()
    if selected_name:
        return selected_name
    for key in ("best_model", "final_model", "selected_model_name", "best_model_name", "model_name"):
        value = metrics.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and str(value.get("name") or "").strip():
            return str(value["name"]).strip()
    return "codex_model"
