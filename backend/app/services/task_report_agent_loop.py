from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_report_formatting import (
    escape_table_cell as _escape_table_cell,
    format_integer as _format_integer,
    format_metric_value as _format_metric_value,
    format_percent as _format_percent,
    markdown_table as _markdown_table,
    status_label as _status_label,
)


def agent_loop(task: TaskRecord) -> dict[str, Any]:
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    loop = requirements.get("agent_loop")
    return dict(loop) if isinstance(loop, dict) else {}


def workflow_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    workflow = agent_loop.get("workflow") if isinstance(agent_loop, dict) else None
    if not isinstance(workflow, list) or not workflow:
        return ["- 尚未记录自动建模执行流程。"]
    rows = []
    for step in workflow:
        if not isinstance(step, dict):
            continue
        rows.append(
            [
                _escape_table_cell(step.get("label") or step.get("key") or "阶段"),
                _escape_table_cell(_status_label(step.get("status"))),
                _escape_table_cell(step.get("detail") or ""),
            ]
        )
    return _markdown_table(["阶段", "状态", "说明"], ["---", "---", "---"], rows)


def checklist_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    checklist = agent_loop.get("checklist") if isinstance(agent_loop, dict) else None
    if not isinstance(checklist, list) or not checklist:
        return ["- 尚未记录任务检查清单。"]
    rows = []
    for item in checklist:
        if not isinstance(item, dict):
            continue
        rows.append(
            [
                _escape_table_cell(item.get("title") or item.get("id") or "检查项"),
                _escape_table_cell(_status_label(item.get("status"))),
                _escape_table_cell(item.get("detail") or ""),
            ]
        )
    return _markdown_table(["检查项", "状态", "证据/说明"], ["---", "---", "---"], rows)


def stop_condition_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    stop_conditions = agent_loop.get("stop_conditions") if isinstance(agent_loop, dict) else None
    if not isinstance(stop_conditions, dict) or not stop_conditions:
        return ["- 尚未记录停止条件。"]
    return _markdown_table(
        ["条件", "当前值"],
        ["---", "---"],
        [
            ["最大模型尝试次数", _format_integer(stop_conditions.get("max_attempts"))],
            ["最小相对改善阈值", _format_percent(stop_conditions.get("min_relative_improvement"))],
            ["最大连续失败/无效尝试", _format_integer(stop_conditions.get("max_consecutive_failed_or_unhelpful_attempts"))],
            ["当前模型尝试次数", _format_integer(stop_conditions.get("current_model_attempts"))],
            ["最近失败/无效尝试次数", _format_integer(stop_conditions.get("recent_failed_or_unhelpful_attempts"))],
            ["是否建议停止", "是" if stop_conditions.get("should_stop") else "否"],
        ],
    )


def quality_gate_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    gates = agent_loop.get("quality_gates")
    if not isinstance(gates, list) or not gates:
        return ["- 尚未形成结果检查结论。"]
    rows = []
    for gate in gates[:8]:
        if not isinstance(gate, dict):
            continue
        title = gate.get("title") or gate.get("id") or "质量检查"
        status = gate.get("status") or "unknown"
        detail = gate.get("detail") or ""
        rows.append([_escape_table_cell(title), _escape_table_cell(_status_label(status)), _escape_table_cell(detail)])
    return _markdown_table(["检查项", "状态", "结论"], ["---", "---", "---"], rows) if rows else ["- 尚未形成结果检查结论。"]


def tuning_attempt_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    attempts = agent_loop.get("tuning_attempts")
    if not isinstance(attempts, list) or not attempts:
        return ["- 尚未记录优化尝试。"]
    lines = [
        "| 轮次 | 类型 | 状态 | 假设 | 动作 | 指标变化 | 说明 |",
        "| ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for attempt in attempts[-8:]:
        if not isinstance(attempt, dict):
            continue
        index = attempt.get("attempt_index")
        kind = attempt.get("kind") or "attempt"
        status = attempt.get("status") or "unknown"
        hypothesis = attempt.get("hypothesis") or ""
        action = attempt.get("action") or ""
        notes = attempt.get("notes") or ""
        lines.append(
            "| "
            + " | ".join(
                [
                    _format_integer(index),
                    _escape_table_cell(kind),
                    _escape_table_cell(_status_label(status)),
                    _escape_table_cell(hypothesis),
                    _escape_table_cell(action),
                    _escape_table_cell(_attempt_metric_change(attempt)),
                    _escape_table_cell(notes),
                ]
            )
            + " |"
        )
    next_improvement = agent_loop.get("next_improvement")
    if isinstance(next_improvement, dict) and next_improvement.get("status") not in {None, "not_needed"}:
        lines.extend(["", f"- 下一步建议：{next_improvement.get('action') or next_improvement.get('detail')}"])
    return lines if len(lines) > 2 else ["- 尚未记录优化尝试。"]


def _attempt_metric_change(attempt: dict[str, Any]) -> str:
    before = attempt.get("metric_before")
    after = attempt.get("metric_after")
    before_text = _metric_snapshot_text(before)
    after_text = _metric_snapshot_text(after)
    if before_text and after_text:
        return f"{before_text} -> {after_text}"
    return after_text or before_text or "未记录"


def _metric_snapshot_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    metric_name = payload.get("metric_name")
    metric_value = payload.get("metric_value")
    if not metric_name and metric_value is None:
        return ""
    return f"{metric_name or 'metric'}={_format_metric_value(metric_value)}"
