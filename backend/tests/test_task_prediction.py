from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskPredictionDemoRequest, TaskRecord
from backend.app.services.task_prediction import _build_generated_code_prediction_response


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-prediction",
        team_id="team-1",
        created_by="user-1",
        name="Prediction Task",
        description="Run generated prediction.",
        label_column="target",
        created_at=now,
        updated_at=now,
    )


def test_generated_code_prediction_response_calls_predict_and_predict_proba(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text(
        "\n".join(
            [
                "def predict(features):",
                "    return {'score': features['age'] + 1}",
                "",
                "def predict_proba(features):",
                "    return {'yes': 0.75, 'no': 0.25}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    response = _build_generated_code_prediction_response(
        _task(),
        TaskPredictionDemoRequest(features={"age": 40, "target": "yes"}),
        generated_code,
    )

    assert response is not None
    assert response.supported is True
    assert response.prediction["features"] == {"age": 40}
    assert response.prediction["label"] == {"score": 41}
    assert response.prediction["probabilities"] == {"yes": 0.75, "no": 0.25}
    assert response.prediction["code_path"] == str(generated_code)


def test_generated_code_prediction_response_rejects_empty_feature_payload(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text("def predict(features):\n    return 'yes'\n", encoding="utf-8")

    response = _build_generated_code_prediction_response(
        _task(),
        TaskPredictionDemoRequest(features={"target": "yes"}),
        generated_code,
    )

    assert response is not None
    assert response.supported is False
    assert response.prediction is None
    assert "预测输入为空" in response.detail
