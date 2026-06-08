from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskPredictionDemoRequest, TaskRecord
from backend.app.services.task_targets import target_columns_from_task


def clean_prediction_features(task: TaskRecord, payload: TaskPredictionDemoRequest) -> dict[str, Any]:
    target_columns = set(target_columns_from_task(task))
    return {
        key: value
        for key, value in payload.features.items()
        if key and key not in target_columns
    }
