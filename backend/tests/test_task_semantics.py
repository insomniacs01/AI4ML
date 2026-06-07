from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models.task import (
    DatasetColumnProfile,
    DatasetProfile,
    TaskRecord,
    TaskSemanticUpdateRequest,
    TaskStatus,
)
from backend.app.services.task_semantics import apply_human_semantic_update


def _task(*, dataset_path: str | None = None, profile: DatasetProfile | None = None) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-semantic",
        team_id="team-1",
        created_by="user-1",
        name="Semantic task",
        description="Fix semantic fields.",
        status=TaskStatus.uploaded,
        dataset_path=dataset_path,
        dataset_profile=profile,
        structured_requirements={"metric_name": "accuracy"},
        created_at=now,
        updated_at=now,
    )


def _payload(label_column: str = "target") -> TaskSemanticUpdateRequest:
    return TaskSemanticUpdateRequest(
        label_column=label_column,
        problem_type="classification",
        metric_name="Macro_F1",
        correction_note="Use the confirmed target.",
    )


def _profile(path: str | None = None) -> DatasetProfile:
    return DatasetProfile(
        filename="train.csv",
        path=path,
        row_count=10,
        column_count=2,
        columns=[
            DatasetColumnProfile(
                name="feature",
                inferred_type="number",
                non_empty_count=10,
                missing_count=0,
                missing_ratio=0,
            ),
            DatasetColumnProfile(
                name="target",
                inferred_type="text",
                non_empty_count=10,
                missing_count=0,
                missing_ratio=0,
            ),
        ],
        preview_rows=[{"feature": "1", "target": "yes"}],
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_apply_human_semantic_update_requires_uploaded_dataset() -> None:
    with pytest.raises(ValueError, match="请先上传数据集"):
        apply_human_semantic_update(_task(), _payload(), corrected_by="user-1")


def test_apply_human_semantic_update_rejects_unknown_profile_target(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    task = _task(dataset_path=str(dataset_dir), profile=_profile(str(dataset_dir)))

    with pytest.raises(ValueError, match="人工修正的目标列不在数据表头中"):
        apply_human_semantic_update(task, _payload("missing_target"), corrected_by="user-1")


def test_apply_human_semantic_update_records_multi_target_directory_semantics(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    task = _task(dataset_path=str(dataset_dir))

    updated = apply_human_semantic_update(task, _payload("Y1,Y2"), corrected_by="user-1")

    assert updated.status == TaskStatus.planning
    assert updated.label_column == "Y1,Y2"
    assert updated.problem_type == "classification"
    assert updated.dataset_profile is None
    assert updated.structured_requirements["metric_name"] == "macro_f1"
    assert updated.structured_requirements["target_columns"] == ["Y1", "Y2"]
    assert updated.structured_requirements["target_definition"] == {
        "target_mode": "multi_target",
        "target_columns": ["Y1", "Y2"],
        "source": "human_correction",
    }
    assert updated.structured_requirements["semantic_correction_history"][-1]["corrected_by"] == "user-1"
