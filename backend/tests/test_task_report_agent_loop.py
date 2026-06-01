from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_report_agent_loop import (
    baseline_experiment_lines,
    compare_task_to_baseline,
    comparison_sentence,
)


def _task() -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-report-agent-loop",
        team_id="team-1",
        created_by="user-1",
        name="Report Agent Loop Task",
        description="Render agent loop report sections.",
        label_column="target",
        problem_type="classification",
        status=TaskStatus.completed,
        created_at=now,
        updated_at=now,
    )


def test_baseline_experiment_lines_render_class_distribution_and_notes() -> None:
    lines = baseline_experiment_lines(
        {
            "baseline": {
                "status": "completed",
                "label": "多数类简单对照",
                "problem_type": "classification",
                "target_column": "target",
                "train_count": 10,
                "validation_count": 4,
                "metric_name": "accuracy",
                "metric_value": 0.7,
                "majority_label": "yes",
                "majority_ratio": 0.7,
                "class_distribution": {"yes": 7, "no": 3},
                "notes": ["使用训练集多数类作为预测。"],
            }
        },
        _task(),
    )

    text = "\n".join(lines)

    assert "| 多数类 | yes |" in text
    assert "| 多数类训练占比 | 70.0% |" in text
    assert "多数类简单对照的训练集类别分布如下。" in text
    assert "- 使用训练集多数类作为预测。" in text


def test_compare_task_to_baseline_reports_lower_metric_improvement() -> None:
    task = _task()
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir="D:/runs/task",
    )

    comparison = compare_task_to_baseline(
        task,
        {"status": "completed", "metric_name": "mae", "metric_value": 3.0},
    )

    assert comparison is not None
    assert comparison["better"] is True
    assert comparison["direction"] == "lower"
    assert comparison["relative_delta"] == 1 / 3
    assert comparison_sentence(comparison) == "模型 mae = 2，简单对照 = 3，相对简单对照降低 33.3%"
