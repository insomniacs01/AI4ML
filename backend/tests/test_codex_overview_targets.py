from backend.app.services.codex_overview_targets import (
    metrics_target_columns,
    metrics_target_metrics,
    metrics_target_text,
    overview_target_columns,
)


def test_overview_target_columns_prefers_top_level_values() -> None:
    payload = {
        "target_columns": "sales， margin",
        "task_summary": {"target_columns": ["fallback"]},
    }

    assert overview_target_columns(payload) == ["sales", "margin"]


def test_metrics_target_columns_prefers_task_values_and_falls_back_to_single_target() -> None:
    assert metrics_target_columns({"task": {"target_columns": [" y1 ", "y2"], "target_column": "fallback"}}) == ["y1", "y2"]
    assert metrics_target_columns({"task": {"target_column": "single_target"}}) == ["single_target"]


def test_metrics_target_text_uses_targets_before_task_mode() -> None:
    metrics = {"task": {"target_mode": "regression"}}

    assert metrics_target_text(metrics, ["y1", "y2"]) == "y1、y2"
    assert metrics_target_text(metrics, []) == "regression"


def test_metrics_target_metrics_uses_first_dict_payload() -> None:
    metrics = {
        "target_metrics": [],
        "metrics_by_target": {"y1": {"mae": 1.2}},
        "per_target_metrics": {"fallback": {"mae": 2.0}},
    }

    assert metrics_target_metrics(metrics) == {"y1": {"mae": 1.2}}
