from __future__ import annotations

from pathlib import Path

from backend.app.services.task_prediction_generated_code import (
    call_generated_code_prediction,
    generated_code_has_predict_contract,
)


def test_generated_code_predict_contract_rejects_top_level_execution(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text(
        "\n".join(
            [
                "print('would execute at import')",
                "",
                "def predict(features):",
                "    return 'yes'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert generated_code_has_predict_contract(generated_code) is False


def test_call_generated_prediction_falls_back_to_raw_features_after_type_error(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text(
        "\n".join(
            [
                "def predict(features):",
                "    if 'target' not in features:",
                "        raise TypeError('raw target required')",
                "    return features['target']",
                "",
            ]
        ),
        encoding="utf-8",
    )

    prediction, failure = call_generated_code_prediction(
        generated_code,
        task_id="task-1",
        features={"age": 40},
        fallback_features={"age": 40, "target": "yes"},
    )

    assert failure is None
    assert prediction is not None
    assert prediction.label == "yes"


def test_call_generated_prediction_reports_import_failure(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text(
        "\n".join(
            [
                "import missing_prediction_dependency",
                "",
                "def predict(features):",
                "    return 'yes'",
                "",
            ]
        ),
        encoding="utf-8",
    )

    prediction, failure = call_generated_code_prediction(
        generated_code,
        task_id="task-1",
        features={"age": 40},
        fallback_features={"age": 40},
    )

    assert prediction is None
    assert failure is not None
    assert failure.kind == "import"
    assert "missing_prediction_dependency" in failure.detail


def test_call_generated_prediction_coerces_json_safe_values(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text(
        "\n".join(
            [
                "class Score:",
                "    def item(self):",
                "        return 0.9",
                "",
                "def predict(features):",
                "    return {'score': Score(), 'columns': tuple(features.keys())}",
                "",
                "def predict_proba(features):",
                "    return {'yes': Score()}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    prediction, failure = call_generated_code_prediction(
        generated_code,
        task_id="task-1",
        features={"age": 40},
        fallback_features={"age": 40},
    )

    assert failure is None
    assert prediction is not None
    assert prediction.label == {"score": 0.9, "columns": ["age"]}
    assert prediction.probabilities == {"yes": 0.9}
