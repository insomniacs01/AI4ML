from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_report_relationships import collect_feature_relationships


def _task(dataset_path: str, *, label_column: str = "target") -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-relationships",
        team_id="team-1",
        created_by="user-1",
        name="Relationship Task",
        description="Analyze feature relationships.",
        label_column=label_column,
        problem_type="regression",
        status=TaskStatus.uploaded,
        dataset_filename="train.csv",
        dataset_path=dataset_path,
        created_at=now,
        updated_at=now,
    )


def test_collect_feature_relationships_scores_numeric_target_features(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "\n".join(
            [
                "feature_a,feature_b,category,target",
                "1,10,A,2",
                "2,8,A,4",
                "3,6,B,6",
                "4,4,B,8",
                "5,2,B,10",
            ]
        ),
        encoding="utf-8",
    )

    entries, notes = collect_feature_relationships(_task(str(dataset)), None)

    assert [entry.feature for entry in entries[:2]] == ["feature_a", "feature_b"]
    assert entries[0].source == "dataset_correlation"
    assert entries[0].importance == 1.0
    assert notes[0].startswith("按与目标列 target 的关系强度排序")


def test_collect_feature_relationships_reports_missing_target_column(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text("feature,target\n1,2\n", encoding="utf-8")

    entries, notes = collect_feature_relationships(_task(str(dataset), label_column="missing"), None)

    assert entries == []
    assert notes == ["数据集中没有找到目标列 missing，无法计算特征与目标列的关系。"]
