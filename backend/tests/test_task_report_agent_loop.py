from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_report_agent_loop import (
    agent_loop,
    checklist_report_lines,
    quality_gate_report_lines,
    stop_condition_report_lines,
    tuning_attempt_report_lines,
    workflow_report_lines,
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
        structured_requirements={"agent_loop": {"workflow": [{"label": "数据检查", "status": "completed"}]}},
        created_at=now,
        updated_at=now,
    )


def test_agent_loop_returns_structured_agent_loop_only() -> None:
    assert agent_loop(_task()) == {"workflow": [{"label": "数据检查", "status": "completed"}]}


def test_agent_loop_report_lines_render_tables_and_fallbacks() -> None:
    assert workflow_report_lines({}) == ["- 尚未记录自动建模执行流程。"]
    assert checklist_report_lines({}) == ["- 尚未记录任务检查清单。"]
    assert quality_gate_report_lines({}) == ["- 尚未形成结果检查结论。"]
    assert stop_condition_report_lines({}) == ["- 尚未记录停止条件。"]
    assert tuning_attempt_report_lines({}) == ["- 尚未记录优化尝试。"]

    payload = {
        "workflow": [{"label": "数据检查", "status": "completed", "detail": "profile ready"}],
        "checklist": [{"title": "目标列确认", "status": "passed", "detail": "target"}],
        "quality_gates": [{"title": "优于简单对照", "status": "passed", "detail": "better"}],
        "tuning_attempts": [
            {
                "attempt_index": 1,
                "kind": "model_run",
                "status": "accepted",
                "hypothesis": "linear baseline",
                "action": "fit ridge",
                "metric_before": {"metric_name": "mae", "metric_value": 3.0},
                "metric_after": {"metric_name": "mae", "metric_value": 2.0},
                "notes": "accepted",
            }
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

    assert "| 数据检查 | 已完成 | profile ready |" in "\n".join(workflow_report_lines(payload))
    assert "| 目标列确认 | 通过 | target |" in "\n".join(checklist_report_lines(payload))
    assert "| 优于简单对照 | 通过 | better |" in "\n".join(quality_gate_report_lines(payload))
    assert "mae=3 -> mae=2" in "\n".join(tuning_attempt_report_lines(payload))
    assert "| 最大模型尝试次数 | 5 |" in "\n".join(stop_condition_report_lines(payload))
