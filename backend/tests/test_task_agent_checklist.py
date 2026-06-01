from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import DatasetColumnProfile, DatasetProfile, TaskRecord, TaskStatus
from backend.app.services.task_agent_checklist import build_checklist


def _task(
    *,
    label_column: str | None = "target",
    profile: DatasetProfile | None = None,
    structured_requirements: dict | None = None,
) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-checklist",
        team_id="team-1",
        created_by="user-1",
        name="Checklist Task",
        description="Build agent checklist.",
        label_column=label_column,
        problem_type="classification",
        status=TaskStatus.uploaded,
        dataset_filename="train.csv",
        dataset_path="D:/datasets/train.csv",
        dataset_profile=profile,
        structured_requirements=structured_requirements or {"metric_name": "accuracy"},
        created_at=now,
        updated_at=now,
    )


def _profile(*, rows: int = 40, columns: list[DatasetColumnProfile] | None = None) -> DatasetProfile:
    return DatasetProfile(
        filename="train.csv",
        path="D:/datasets/train.csv",
        row_count=rows,
        column_count=len(columns or []),
        columns=columns or [],
        generated_at=datetime.now(timezone.utc),
    )


def _column(name: str, *, missing_ratio: float = 0.0) -> DatasetColumnProfile:
    return DatasetColumnProfile(
        name=name,
        inferred_type="text",
        non_empty_count=10,
        missing_count=0,
        missing_ratio=missing_ratio,
    )


def test_checklist_blocks_target_column_missing_from_profile() -> None:
    checklist = build_checklist(_task(profile=_profile(columns=[_column("feature")])))

    by_id = {item["id"]: item for item in checklist}
    assert by_id["target_in_columns"]["status"] == "blocked"
    assert by_id["target_in_columns"]["evidence"] == "target"
    assert "不在当前数据表头中" in by_id["target_in_columns"]["detail"]


def test_checklist_keeps_target_column_passed_without_profile() -> None:
    checklist = build_checklist(_task(profile=None))

    by_id = {item["id"]: item for item in checklist}
    assert by_id["dataset_profile"]["status"] == "blocked"
    assert by_id["target_in_columns"]["status"] == "passed"


def test_checklist_accepts_multiple_target_columns_from_profile() -> None:
    checklist = build_checklist(
        _task(
            label_column="Y1,Y2",
            profile=_profile(columns=[_column("X1"), _column("Y1"), _column("Y2")]),
        )
    )

    by_id = {item["id"]: item for item in checklist}
    assert by_id["target_column"]["status"] == "passed"
    assert by_id["target_in_columns"]["status"] == "passed"
    assert by_id["target_in_columns"]["evidence"] == ["Y1", "Y2"]


def test_checklist_accepts_multiple_target_columns_from_structured_requirements() -> None:
    checklist = build_checklist(
        _task(
            label_column=None,
            profile=_profile(columns=[_column("X1"), _column("Y1"), _column("Y2")]),
            structured_requirements={"metric_name": "rmse", "target_columns_hint": ["Y1", "Y2"]},
        )
    )

    by_id = {item["id"]: item for item in checklist}
    assert by_id["target_column"]["status"] == "passed"
    assert by_id["target_in_columns"]["status"] == "passed"
    assert by_id["target_in_columns"]["evidence"] == ["Y1", "Y2"]


def test_checklist_blocks_missing_member_of_multiple_target_columns() -> None:
    checklist = build_checklist(
        _task(
            label_column="Y1,Y2",
            profile=_profile(columns=[_column("X1"), _column("Y1")]),
        )
    )

    by_id = {item["id"]: item for item in checklist}
    assert by_id["target_in_columns"]["status"] == "blocked"
    assert by_id["target_in_columns"]["evidence"] == ["Y1", "Y2"]
    assert "Y2" in by_id["target_in_columns"]["detail"]


def test_checklist_reports_profile_risks() -> None:
    checklist = build_checklist(
        _task(
            profile=_profile(
                rows=20,
                columns=[
                    _column("feature", missing_ratio=0.3),
                    _column("target"),
                ],
            )
        )
    )

    by_id = {item["id"]: item for item in checklist}
    assert by_id["missing_values"]["status"] == "warning"
    assert "feature(30%)" in by_id["missing_values"]["detail"]
    assert by_id["sample_size"]["status"] == "warning"
