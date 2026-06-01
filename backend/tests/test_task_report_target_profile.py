from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import DatasetProfile, TaskRecord, TaskStatus
from backend.app.services.task_report_target_profile import build_target_profile


def _task(*, dataset_path: str | None = None, label_column: str = "target") -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-target-profile",
        team_id="team-1",
        created_by="user-1",
        name="Target Profile Task",
        description="Profile a target column.",
        label_column=label_column,
        problem_type="regression",
        status=TaskStatus.uploaded,
        dataset_filename="train.csv",
        dataset_path=dataset_path,
        created_at=now,
        updated_at=now,
    )


def test_build_target_profile_summarizes_numeric_dataset_column(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text("feature,target\nA,1\nB,2\nC,3\nD,4\nE,5\n", encoding="utf-8")

    profile = build_target_profile(_task(dataset_path=str(dataset)), None)

    assert profile["status"] == "available"
    assert profile["source"] == "dataset_file"
    assert profile["kind"] == "numeric"
    assert profile["count"] == 5
    assert profile["mean"] == 3.0
    assert profile["median"] == 3.0


def test_build_target_profile_reports_missing_dataset_target_column(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text("feature,other\nA,1\n", encoding="utf-8")

    profile = build_target_profile(_task(dataset_path=str(dataset), label_column="target"), None)

    assert profile == {
        "status": "unavailable",
        "target_column": "target",
        "detail": "CSV 表头中没有找到目标列 target。",
    }


def test_build_target_profile_falls_back_to_preview_rows() -> None:
    now = datetime.now(timezone.utc)
    profile = DatasetProfile(
        filename="train.csv",
        row_count=3,
        column_count=1,
        target_column="target",
        generated_at=now,
        columns=[],
        preview_rows=[
            {"target": "yes"},
            {"target": "no"},
            {"target": "yes"},
        ],
    )

    result = build_target_profile(_task(dataset_path=None), profile)

    assert result["status"] == "available"
    assert result["source"] == "dataset_preview"
    assert result["kind"] == "categorical"
    assert result["class_count"] == 2
    assert result["top_values"][0] == {"value": "yes", "count": 2, "ratio": 2 / 3}
