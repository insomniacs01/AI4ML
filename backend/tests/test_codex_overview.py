from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.codex_overview import _overview_baseline_metric, build_codex_overview_from_artifacts


def test_overview_baseline_metric_uses_requested_split_with_candidate_fallback() -> None:
    metrics = {
        "baselines": {
            "mean": {"validation": {"mae": 2.0}, "test": {"mae": 3.0}},
            "median": {"test": {"mae": 1.5}},
            "invalid": {"validation": {"mae": "not-a-number"}},
        }
    }

    assert _overview_baseline_metric(metrics, "mae", "validation") == ("median", 1.5)


def test_overview_baseline_metric_picks_higher_baseline_for_higher_is_better_metric() -> None:
    metrics = {
        "baselines": {
            "majority": {"test": {"accuracy": 0.8}},
            "random": {"validation": {"accuracy": 0.7}},
        }
    }

    assert _overview_baseline_metric(metrics, "accuracy", None) == ("majority", 0.8)


def test_derived_overview_result_checks_use_metrics_and_workspace(tmp_path: Path) -> None:
    metrics = {
        "created_at": "2026-01-01T00:00:00+00:00",
        "selected_model": {
            "name": "ridge",
            "test": {"mae": 2.0},
            "feature_importance": {"age": 0.8, "income": -0.2},
        },
        "baselines": {"mean": {"test": {"mae": 3.0}}},
        "split": {"strategy": "holdout"},
        "diagnostics": {"leakage": {"interpretation": "review target leakage"}},
        "artifacts": {"predict_py": "output/predict.py", "prediction_csv": "output/predictions.csv"},
        "dataset": {"raw_rows": 120},
    }

    overview = build_codex_overview_from_artifacts(
        {
            "workspace": {"path": str(tmp_path)},
            "metrics": metrics,
        }
    )

    checks = {item["name"]: item for item in overview["result_checks"]}
    assert checks["baseline_comparison"]["status"] == "passed"
    assert checks["baseline_comparison"]["evidence"] == "mean: mae = 3"
    assert checks["validation_split"]["status"] == "passed"
    assert checks["validation_split"]["evidence"] == "holdout"
    assert checks["leakage_check"]["status"] == "warning"
    assert checks["leakage_check"]["detail"] == "review target leakage"
    assert checks["artifact_consistency"]["status"] == "passed"
    assert checks["artifact_consistency"]["evidence"] == str(tmp_path)
    assert checks["prediction_entrypoint"]["status"] == "passed"
    assert checks["prediction_entrypoint"]["evidence"] == "output/predict.py"
    assert checks["data_quality"]["status"] == "passed"
    assert checks["data_quality"]["evidence"] == "rows=120"
    assert [item["name"] for item in overview["key_factors"]] == ["age", "income"]
    assert overview["key_factors"][0]["direction"] == "positive"
    assert overview["key_factors"][1]["direction"] == "negative"


def test_derived_overview_optimization_records_compare_worker_metrics(tmp_path: Path) -> None:
    optimization_dir = tmp_path / "work" / "subagents" / "optimization_worker"
    optimization_dir.mkdir(parents=True)
    (optimization_dir / "optimization_results.json").write_text(
        json.dumps(
            {
                "parent_first_round_reference": {"validation_mae": 3.0},
                "best_candidate": {
                    "candidate": "candidate-a",
                    "route": "drop noisy columns",
                    "metrics": {"validation": {"mae": 2.0}},
                },
                "candidate_results": [{"candidate": "candidate-a"}, {"candidate": "candidate-b"}],
            }
        ),
        encoding="utf-8",
    )
    metrics = {
        "selected_model": {"name": "ridge", "test": {"mae": 2.0}},
        "diagnostics": {"bounded_optimization_summary": "Kept search within budget."},
    }

    overview = build_codex_overview_from_artifacts(
        {
            "workspace": {"path": str(tmp_path)},
            "metrics": metrics,
        }
    )

    records = overview["optimization_records"]
    assert records[0]["name"] == "bounded_optimization"
    assert records[0]["detail"] == "Kept search within budget."
    assert records[1]["name"] == "candidate-a"
    assert records[1]["change"] == "drop noisy columns"
    assert records[1]["before_metric"] == 3.0
    assert records[1]["after_metric"] == 2.0
    assert records[1]["metric_name"] == "mae"
    assert records[1]["result"] == "improved"
    assert records[1]["detail"] == "optimization_worker 评估了 2 个候选配置。"


def test_derived_overview_key_factors_fall_back_to_error_analysis() -> None:
    metrics = {
        "selected_model": {"name": "ridge", "test": {"mae": 2.0}},
        "error_analysis": {
            "by_source_category_test": [
                {"Source_Category": "A", "signed_log_mae": 1.2},
                {"Source_Category": "B", "signed_log_mae": 2.5},
                {"Source_Category": "", "signed_log_mae": 9.9},
            ]
        },
    }

    overview = build_codex_overview_from_artifacts({"metrics": metrics})

    factors = overview["key_factors"]
    assert [item["name"] for item in factors] == ["B", "A"]
    assert factors[0]["source"] == "error_analysis"
    assert factors[0]["is_model_feature_importance"] is False
    assert factors[0]["direction"] == "unknown"
    assert "signed_log_mae = 2.5" in factors[0]["evidence"]
