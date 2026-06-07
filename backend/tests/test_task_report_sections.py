from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import DatasetColumnProfile, DatasetProfile, FeatureImportanceEntry, RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_report_narrative import abstract_lines
from backend.app.services.task_report_sections import build_report_markdown


def test_abstract_lines_preserve_summary_sentence_format() -> None:
    now = datetime.now(timezone.utc)
    profile = DatasetProfile(
        filename="train.csv",
        row_count=5,
        column_count=2,
        generated_at=now,
        columns=[],
    )
    task = TaskRecord(
        id="task-abstract",
        team_id="team-1",
        created_by="user-1",
        name="Report Task",
        description="Train a model and explain the result.",
        label_column="target",
        problem_type="regression",
        status=TaskStatus.completed,
        last_run=RunSummary(
            best_model="ridge",
            metric_name="mae",
            metric_value=2.0,
            validation_score=-2.0,
            leaderboard=[],
            output_dir="D:/tmp/report-task",
        ),
        created_at=now,
        updated_at=now,
    )
    agent_loop = {
        "baseline": {
            "status": "completed",
            "label": "均值预测基线",
            "metric_name": "mae",
            "metric_value": 3.0,
        }
    }
    feature_importance = [
        FeatureImportanceEntry(feature="age", importance=0.45, source="model"),
        FeatureImportanceEntry(feature="income", importance=0.32, source="model"),
    ]

    lines = abstract_lines(task, profile, agent_loop, feature_importance, candidate_count=2)

    assert lines == [
        "本报告围绕任务“Report Task”整理自动建模全过程。数据集包含 5 行、2 列，目标列为 `target`，任务类型为 regression。",
        "系统首先建立简单对照：均值预测基线，mae = 3。",
        "自动建模阶段共解析到 2 个候选模型，当前最优模型为 ridge，mae = 2；模型 mae = 2，简单对照 = 3，相对简单对照降低 33.3%。",
        "解释性分析中，排名靠前的特征包括：age(0.45)、income(0.32)。",
    ]


def test_report_includes_agent_loop_quality_tuning_and_stop_sections(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    task = TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Report Task",
        description="Train a model and explain the result.",
        label_column="target",
        problem_type="regression",
        status=TaskStatus.completed,
        dataset_filename="train.csv",
        dataset_path=str(tmp_path / "train.csv"),
        last_run=RunSummary(
            best_model="ridge",
            metric_name="mae",
            metric_value=2.0,
            validation_score=-2.0,
            leaderboard=[{"model": "ridge", "metric_value": 2.0}],
            output_dir=str(tmp_path),
        ),
        structured_requirements={
            "agent_loop": {
                "workflow": [
                    {"label": "简单对照测试", "status": "completed", "detail": "baseline ready"},
                ],
                "checklist": [
                    {"title": "预测目标已确认", "status": "passed", "detail": "target"},
                ],
                "baseline": {
                    "status": "completed",
                    "label": "均值预测基线",
                    "problem_type": "regression",
                    "target_column": "target",
                    "metric_name": "mae",
                    "metric_value": 3.0,
                    "train_count": 8,
                    "validation_count": 2,
                },
                "quality_gates": [
                    {"title": "模型优于简单对照", "status": "passed", "detail": "better"},
                ],
                "tuning_attempts": [
                    {
                        "attempt_index": 1,
                        "kind": "model_run",
                        "status": "accepted",
                        "hypothesis": "train",
                        "action": "fit ridge",
                        "metric_before": {"metric_name": "mae", "metric_value": 3.0},
                        "metric_after": {"metric_name": "mae", "metric_value": 2.0},
                        "notes": "accepted",
                    },
                ],
                "stop_conditions": {
                    "max_attempts": 5,
                    "min_relative_improvement": 0.01,
                    "max_consecutive_failed_or_unhelpful_attempts": 2,
                    "current_model_attempts": 1,
                    "recent_failed_or_unhelpful_attempts": 0,
                    "should_stop": False,
                },
            }
        },
        created_at=now,
        updated_at=now,
    )

    markdown = build_report_markdown(
        task=task,
        generated_at=now,
        dataset_profile=None,
        feature_importance=[],
        result_summary=["Best model: ridge"],
        data_quality_notes=["No profile."],
        limitation_notes=["Needs holdout validation."],
        relationship_notes=[],
        using_artifact_importance=False,
    )

    assert "### 6.1 结果检查" in markdown
    assert "模型优于简单对照" in markdown
    assert "mae=3 -> mae=2" in markdown
    assert "最大模型尝试次数" in markdown
    assert (tmp_path / "final_report.md").read_text(encoding="utf-8") == markdown


def test_report_renders_dataset_profile_overview_and_field_quality() -> None:
    now = datetime.now(timezone.utc)
    profile = DatasetProfile(
        filename="train|raw.csv",
        row_count=5,
        column_count=2,
        target_column="target",
        generated_at=now,
        columns=[
            DatasetColumnProfile(
                name="feature|one",
                inferred_type="number",
                non_empty_count=4,
                missing_count=1,
                missing_ratio=0.2,
                sample_values=["1|A", "2"],
            ),
            DatasetColumnProfile(
                name="target",
                inferred_type="number",
                non_empty_count=5,
                missing_count=0,
                missing_ratio=0.0,
                sample_values=["1", "2", "3"],
            ),
        ],
        preview_rows=[
            {"feature|one": "1|A", "target": "1"},
            {"feature|one": "2", "target": "2"},
            {"feature|one": "3", "target": "3"},
            {"feature|one": "4", "target": "4"},
            {"feature|one": "", "target": "5"},
        ],
    )
    task = TaskRecord(
        id="task-2",
        team_id="team-1",
        created_by="user-1",
        name="Dataset Report Task",
        description="Profile a dataset.",
        label_column="target",
        problem_type="regression",
        status=TaskStatus.uploaded,
        dataset_filename="train|raw.csv",
        structured_requirements={"metric_name": "mae"},
        created_at=now,
        updated_at=now,
    )

    markdown = build_report_markdown(
        task=task,
        generated_at=now,
        dataset_profile=profile,
        feature_importance=[],
        result_summary=["No run yet."],
        data_quality_notes=["Profile available."],
        limitation_notes=["No model yet."],
        relationship_notes=[],
        using_artifact_importance=False,
    )

    assert "| 文件名 | train\\|raw.csv |" in markdown
    assert "- 目标列画像：非空样本 5，不同取值 5。" in markdown
    assert "| 均值 | 3 |" in markdown
    assert "| feature\\|one | number | 4 | 1 | 20.0% | 1\\|A、2 |" in markdown
