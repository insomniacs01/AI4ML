from backend.app.services.codex_overview_charts import actual_vs_predicted_points, metric_series


def test_actual_vs_predicted_points_uses_supported_value_keys_and_skips_invalid_rows() -> None:
    metrics = {
        "top_error_cases": [
            {"record_id": "r1", "Value": "10", "predicted_value": "8.5"},
            {"actual": 5, "prediction": 4},
            {"actual_value": "bad", "predicted": 1},
            ["not-a-row"],
        ]
    }

    assert actual_vs_predicted_points(metrics) == [
        {"x": "r1", "actual": 10.0, "predicted": 8.5},
        {"x": "2", "actual": 5.0, "predicted": 4.0},
    ]


def test_metric_series_reads_candidate_dicts_and_split_priority() -> None:
    metrics = {
        "candidate_models": {
            "ridge": {"validation": {"mae": 3.0}, "test": {"mae": 2.0}},
            "lasso": {"test": {"mae": 1.5}},
            "bad": {"test": {"mae": "not-a-number"}},
            "not-a-dict": [],
        }
    }

    assert metric_series(metrics, "mae") == [
        {"label": "ridge", "value": 3.0},
        {"label": "lasso", "value": 1.5},
    ]


def test_metric_series_reads_candidate_lists_and_limits_results() -> None:
    metrics = {
        "candidate_models": [
            {"name": f"model-{index}", "test": {"accuracy": index / 100}}
            for index in range(1, 15)
        ]
    }

    series = metric_series(metrics, "accuracy")

    assert len(series) == 12
    assert series[0] == {"label": "model-1", "value": 0.01}
    assert series[-1] == {"label": "model-12", "value": 0.12}
