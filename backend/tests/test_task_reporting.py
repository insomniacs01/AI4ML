from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunSummary, TaskRecord
from backend.app.services.task_report_codex_summary import codex_result_summary


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-reporting",
        team_id="team-1",
        created_by="user-1",
        name="Reporting Task",
        description="Build report summary.",
        created_at=now,
        updated_at=now,
    )


def test_codex_result_summary_uses_selected_model_metric_and_rationale() -> None:
    metrics = {
        "selected_model": {
            "name": "LightGBM",
            "cross_validation": {"macro_f1_mean": "0.81234", "accuracy": 0.9},
            "selection_rationale": " Best validation tradeoff. ",
        }
    }

    assert codex_result_summary(_task(), metrics) == [
        "最佳模型：LightGBM",
        "评价指标：macro_f1_mean = 0.81234",
        "Best validation tradeoff.",
    ]


def test_codex_result_summary_prefers_task_last_run_metric_and_model_fallback() -> None:
    task = _task()
    task.last_run = RunSummary(
        best_model="RandomForest",
        metric_name="mae",
        metric_value=2.34567,
        output_dir="workspace",
    )

    assert codex_result_summary(task, {"selected_model": {"holdout": {"rmse": 9.9}}}) == [
        "最佳模型：RandomForest",
        "评价指标：mae = 2.34567",
    ]
