from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    DatasetColumnProfile,
    DatasetProfile,
    FeatureImportanceEntry,
    RunSummary,
    TaskRecord,
)
from backend.app.services.task_report_notes import (
    build_data_quality_notes,
    build_limitation_notes,
    build_result_summary,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task() -> TaskRecord:
    return TaskRecord(
        id="task-report-notes",
        team_id="team-1",
        created_by="user-1",
        name="Report Notes Task",
        description="Build report notes.",
        created_at=NOW,
        updated_at=NOW,
    )


def _profile(*, row_count: int = 200) -> DatasetProfile:
    return DatasetProfile(
        filename="dataset.csv",
        path="dataset.csv",
        row_count=row_count,
        column_count=3,
        target_column="target",
        generated_at=NOW,
        columns=[
            DatasetColumnProfile(
                name="age",
                inferred_type="integer",
                non_empty_count=90,
                missing_count=10,
                missing_ratio=0.10,
                sample_values=["40"],
            ),
            DatasetColumnProfile(
                name="income",
                inferred_type="number",
                non_empty_count=80,
                missing_count=20,
                missing_ratio=0.20,
                sample_values=["1000"],
            ),
        ],
    )


def test_build_result_summary_uses_relationship_notes_without_successful_run() -> None:
    summary = build_result_summary(
        _task(),
        feature_importance=[],
        relationship_notes=["note-1", "note-2", "note-3", "note-4"],
        using_artifact_importance=False,
    )

    assert summary == [
        "当前任务还没有成功的自动建模结果；本报告只能给出数据与特征关系诊断，不能作为最终模型验收报告。",
        "note-1",
        "note-2",
        "note-3",
    ]


def test_build_result_summary_describes_successful_run_and_feature_source() -> None:
    task = _task()
    task.last_run = RunSummary(
        best_model="RandomForest",
        metric_name="mae",
        metric_value=2.34567,
        leaderboard=[{"model": "rf"}, {"model": "ridge"}],
        output_dir="runs/task-1",
    )

    summary = build_result_summary(
        task,
        feature_importance=[FeatureImportanceEntry(feature="age", importance=0.75)],
        relationship_notes=[],
        using_artifact_importance=True,
    )

    assert summary == [
        "最佳模型为 RandomForest。",
        "主要指标 mae = 2.34567。",
        "本次成功解析到 2 个候选模型结果。",
        "结果文件目录：runs/task-1。",
        "按模型给出的特征重要性看，最重要/最相关的特征包括：age(0.75)。",
    ]


def test_build_data_quality_notes_reports_missing_values_and_target() -> None:
    assert build_data_quality_notes(_profile()) == [
        "数据集包含 200 行、3 列。",
        "存在缺失值的字段包括：income(20.0%)、age(10.0%)。",
        "当前目标列为 target。",
    ]
    assert build_data_quality_notes(None) == ["当前没有可读取的数据集画像。"]


def test_build_limitation_notes_combines_small_data_explainability_and_candidate_warnings() -> None:
    task = _task()
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="rmse",
        metric_value=1.0,
        leaderboard=[{"model": "ridge"}],
        output_dir="runs/task-1",
    )

    notes = build_limitation_notes(
        task,
        _profile(row_count=50),
        [],
        relationship_notes=["未找到可计算的目标列关系。"],
        using_artifact_importance=False,
    )

    assert notes == [
        "数据行数较少，验证指标可能对划分方式敏感。",
        "当前没有可解析的特征重要性文件，也无法从数据集中计算稳定的特征关系，因此模型解释性不足。",
        "未找到可计算的目标列关系。",
        "候选模型数量较少，模型选择结论的稳定性有限。",
    ]
