from __future__ import annotations

from pathlib import Path

from backend.app.services.codex_metrics import build_codex_run_summary, leaderboard_from_metrics, primary_metric


def test_codex_summary_reads_selected_model_metrics_container(tmp_path: Path) -> None:
    metrics = {
        "selected_model": {
            "name": "RandomForestRegressor",
            "metrics": {"RMSE": 0.3678575579623178, "MAE": 0.3119085},
            "selection_metric": "RMSE",
        },
        "candidates": [
            {"name": "Ridge Regression", "metrics": {"RMSE": 0.37179281848327234}},
            {"name": "RandomForestRegressor", "metrics": {"RMSE": 0.3678575579623178}},
        ],
    }

    summary = build_codex_run_summary(str(tmp_path), metrics)

    assert summary is not None
    assert summary.best_model == "RandomForestRegressor"
    assert summary.metric_name == "RMSE"
    assert summary.metric_value == 0.3678575579623178
    assert len(summary.leaderboard) == 2


def test_codex_summary_reads_validation_metrics_container(tmp_path: Path) -> None:
    metrics = {
        "selected_model": {
            "name": "logistic_regression",
            "validation_metrics": {"accuracy": 1.0, "macro_f1": 0.98},
            "cross_validation": {"macro_f1": {"mean": 0.97}},
        },
        "candidate_models": {
            "logistic_regression": {"validation_metrics": {"accuracy": 1.0, "macro_f1": 0.98}},
            "random_forest": {"validation_metrics": {"accuracy": 0.96, "macro_f1": 0.95}},
        },
    }

    summary = build_codex_run_summary(str(tmp_path), metrics)

    assert summary is not None
    assert summary.best_model == "logistic_regression"
    assert summary.metric_name == "macro_f1"
    assert summary.metric_value == 0.98
    assert [row["model"] for row in summary.leaderboard] == ["logistic_regression", "random_forest"]


def test_codex_summary_resolves_string_final_model_from_models(tmp_path: Path) -> None:
    metrics = {
        "final_model": "target_encoded_hgb_basic",
        "models": {
            "target_encoded_hgb_basic": {
                "validation": {"signed_log_mae": 0.6044653532568266},
                "test": {"signed_log_mae": 0.6152404314242488},
            },
            "target_encoded_hgb_optimized": {
                "validation": {"signed_log_mae": 0.8251720260525485},
                "test": {"signed_log_mae": 0.8485210096939977},
            },
        },
    }

    summary = build_codex_run_summary(str(tmp_path), metrics)

    assert summary is not None
    assert summary.best_model == "target_encoded_hgb_basic"
    assert summary.metric_name == "signed_log_mae"
    assert summary.metric_value == 0.6152404314242488


def test_codex_summary_falls_back_to_overview_prediction_error(tmp_path: Path) -> None:
    summary = build_codex_run_summary(
        str(tmp_path),
        {},
        overview={"prediction_error": {"primary_metric": "MAE", "value": 0.42}},
    )

    assert summary is not None
    assert summary.metric_name == "MAE"
    assert summary.metric_value == 0.42


def test_primary_metric_reads_cross_validation_mean() -> None:
    metric_name, metric_value = primary_metric(
        {"name": "ridge", "cross_validation": {"macro_f1": {"mean": 0.91}}},
        {"primary_metric": "macro_f1"},
    )

    assert metric_name == "macro_f1"
    assert metric_value == 0.91


def test_leaderboard_accepts_candidates_list() -> None:
    rows = leaderboard_from_metrics({
        "candidates": [
            {"name": "linear", "metrics": {"RMSE": 0.5}, "selection_metric": "RMSE"},
            {"name": "forest", "metrics": {"RMSE": 0.4}, "selection_metric": "RMSE"},
        ],
    })

    assert [row.model for row in rows] == ["linear", "forest"]
    assert [row.validation_score for row in rows] == [0.5, 0.4]
