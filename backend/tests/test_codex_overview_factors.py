from backend.app.services.codex_overview_factors import derive_key_factors, feature_importance_factors


def test_feature_importance_factors_sort_by_absolute_importance_and_skip_invalid() -> None:
    factors = feature_importance_factors({"age": 0.2, "income": -0.9, "bad": "x", 123: 1.0})

    assert [item["name"] for item in factors] == ["income", "age"]
    assert factors[0]["direction"] == "negative"
    assert factors[1]["direction"] == "positive"


def test_derive_key_factors_falls_back_to_error_analysis() -> None:
    metrics = {
        "selected_model": {},
        "error_analysis": {
            "by_source_category_test": [
                {"Source_Category": "A", "signed_log_mae": 1.2},
                {"Source_Category": "B", "signed_log_mae": 2.5},
                {"Source_Category": "", "signed_log_mae": 9.9},
            ]
        },
    }

    factors = derive_key_factors(metrics)

    assert [item["name"] for item in factors] == ["B", "A"]
    assert factors[0]["source"] == "error_analysis"
    assert "signed_log_mae = 2.5" in factors[0]["evidence"]
