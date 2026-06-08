from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskPredictionDemoRequest, TaskRecord
from backend.app.services.task_prediction_inputs import clean_prediction_features


def _task(*, label_column: str | None = "target", structured_requirements: dict | None = None) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-prediction",
        team_id="team-1",
        created_by="user-1",
        name="Prediction Task",
        description="Run prediction.",
        label_column=label_column,
        structured_requirements=structured_requirements,
        created_at=now,
        updated_at=now,
    )


def test_clean_prediction_features_removes_label_column() -> None:
    features = clean_prediction_features(
        _task(label_column="target"),
        TaskPredictionDemoRequest(features={"age": 40, "target": "yes", "": "ignored"}),
    )

    assert features == {"age": 40}


def test_clean_prediction_features_removes_structured_multi_targets() -> None:
    features = clean_prediction_features(
        _task(label_column=None, structured_requirements={"target_columns_hint": ["Y1", "Y2"]}),
        TaskPredictionDemoRequest(features={"X1": 1, "Y1": 10, "Y2": 20}),
    )

    assert features == {"X1": 1}
