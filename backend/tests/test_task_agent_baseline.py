from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_agent_baseline import compute_baseline


def _task(dataset_path: Path, *, problem_type: str, metric_name: str) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Task",
        description="Train a tabular model.",
        label_column="target",
        problem_type=problem_type,
        status=TaskStatus.uploaded,
        dataset_filename=dataset_path.name,
        dataset_path=str(dataset_path),
        structured_requirements={"metric_name": metric_name},
        created_at=now,
        updated_at=now,
    )


def test_regression_baseline_resolves_r2_metric(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "feature,target\n"
        "a,1\n"
        "b,2\n"
        "c,3\n"
        "d,4\n"
        "e,5\n"
        "f,6\n"
        "g,7\n"
        "h,8\n"
        "i,9\n"
        "j,10\n",
        encoding="utf-8",
    )

    baseline = compute_baseline(_task(dataset, problem_type="regression", metric_name="r2"))

    assert baseline["status"] == "completed"
    assert baseline["metric_name"] == "r2"
    assert baseline["metric_value"] == -1.0
    assert baseline["validation_score"] == -1.0
    assert baseline["direction"] == "higher"


def test_classification_baseline_resolves_binary_f1_metric(tmp_path) -> None:
    dataset = _write_binary_classification_dataset(tmp_path)

    baseline = compute_baseline(_task(dataset, problem_type="classification", metric_name="f1"))

    assert baseline["status"] == "completed"
    assert baseline["metric_name"] == "f1"
    assert math.isclose(baseline["metric_value"], 2 / 3)
    assert math.isclose(baseline["validation_score"], 2 / 3)
    assert baseline["majority_label"] == "yes"
    assert baseline["class_distribution"] == {"yes": 6, "no": 2}


def test_classification_baseline_resolves_balanced_accuracy_metric(tmp_path) -> None:
    dataset = _write_binary_classification_dataset(tmp_path)

    baseline = compute_baseline(_task(dataset, problem_type="classification", metric_name="balanced_accuracy"))

    assert baseline["status"] == "completed"
    assert baseline["metric_name"] == "balanced_accuracy"
    assert baseline["metric_value"] == 0.5
    assert baseline["validation_score"] == 0.5


def _write_binary_classification_dataset(tmp_path) -> Path:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "feature,target\n"
        "a,no\n"
        "b,yes\n"
        "c,yes\n"
        "d,yes\n"
        "e,no\n"
        "f,yes\n"
        "g,yes\n"
        "h,no\n"
        "i,yes\n"
        "j,yes\n",
        encoding="utf-8",
    )
    return dataset
