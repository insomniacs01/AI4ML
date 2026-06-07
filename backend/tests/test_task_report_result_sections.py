from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import FeatureImportanceEntry, RunAttempt, RunSummary, TaskRecord
from backend.app.services.task_artifact_index import RunArtifactIndex
from backend.app.services.task_report_result_sections import (
    artifact_report_lines,
    feature_importance_table_lines,
    model_result_lines,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_model_result_lines_render_leaderboard_aliases_and_metrics() -> None:
    task = _task(
        last_run=RunSummary(
            best_model="ridge",
            metric_name="mae",
            metric_value=2.5,
            validation_score=-2.5,
            output_dir="runs/task-1",
            leaderboard=[
                {"name": "ridge|v1", "score_val": -2.5, "metric_value": 2.5, "fit_time": 1.2, "pred_time": 0.1}
            ],
        )
    )

    lines = model_result_lines(task)

    assert "- 最佳模型：ridge" in lines
    assert "| 1 | ridge\\|v1 | -2.5 | 2.5 | 1.2 | 0.1 |" in "\n".join(lines)


def test_model_result_lines_show_last_failed_attempt_without_successful_run() -> None:
    task = _task(last_run_attempt=RunAttempt(output_dir="runs/task-1", diagnosis_detail="Training failed."))

    lines = model_result_lines(task)

    assert lines == [
        "- 暂无成功模型结果。",
        "- 最近运行目录：runs/task-1。",
        "- 最近诊断：Training failed.",
    ]


def test_artifact_report_lines_render_found_and_missing_artifacts(tmp_path: Path) -> None:
    run_summary = tmp_path / "run_summary.json"
    feature_importance = tmp_path / "feature|importance.csv"
    index = RunArtifactIndex(
        output_dir=tmp_path,
        run_summary_path=run_summary,
        feature_importance_paths=[feature_importance],
    )

    lines = artifact_report_lines(index)
    markdown = "\n".join(lines)

    assert "| 结果摘要 | 已找到 |" in markdown
    assert "feature\\|importance.csv" in markdown
    assert "| 生成代码 | 未找到 | 未记录 |" in markdown


def test_feature_importance_table_lines_escape_feature_and_source_names() -> None:
    lines = feature_importance_table_lines(
        [FeatureImportanceEntry(feature="age|income", importance=0.75, source="model|card")]
    )

    assert "| 1 | age\\|income | 0.75 | model\\|card |" in "\n".join(lines)


def _task(**overrides) -> TaskRecord:
    values = {
        "id": "task-1",
        "team_id": "team-1",
        "created_by": "user-1",
        "name": "Task",
        "description": "Train a model.",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return TaskRecord(**values)
