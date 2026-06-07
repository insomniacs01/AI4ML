from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_agent_baseline_metrics import baseline_completed
from backend.app.services.task_agent_checklist import profile_summary
from backend.app.services.task_agent_quality import quality_detail, quality_status


def build_workflow(task: TaskRecord, loop: dict[str, Any]) -> list[dict[str, Any]]:
    checklist = _loop_list(loop, "checklist")
    baseline = _loop_dict(loop, "baseline")
    quality_gates = _loop_list(loop, "quality_gates")
    next_improvement = _loop_dict(loop, "next_improvement")
    return [
        _requirement_step(task),
        _checklist_step(checklist),
        _data_profiling_step(task),
        _baseline_step(baseline),
        _modeling_step(task),
        _quality_step(quality_gates),
        _tuning_step(task, next_improvement),
        _final_report_step(task),
    ]


def _loop_list(loop: dict[str, Any], key: str) -> list[Any]:
    value = loop.get(key)
    return value if isinstance(value, list) else []


def _loop_dict(loop: dict[str, Any], key: str) -> dict[str, Any]:
    value = loop.get(key)
    return value if isinstance(value, dict) else {}


def _requirement_step(task: TaskRecord) -> dict[str, str]:
    return _workflow_step(
        "requirement_reading",
        "需求理解",
        "completed" if task.description else "pending",
        "读取任务名称、业务描述和 CSV 上下文。",
    )


def _checklist_step(checklist: list[Any]) -> dict[str, str]:
    return _workflow_step(
        "task_checklist",
        "任务检查清单",
        _checklist_status(checklist),
        "确认数据、目标列、问题类型、指标和基础风险。",
    )


def _checklist_status(checklist: list[Any]) -> str:
    if any(item.get("status") == "blocked" for item in checklist):
        return "blocked"
    return "completed" if checklist else "pending"


def _data_profiling_step(task: TaskRecord) -> dict[str, str]:
    return _workflow_step(
        "data_profiling",
        "数据体检",
        "completed" if task.dataset_profile else "pending",
        profile_summary(task.dataset_profile),
    )


def _baseline_step(baseline: dict[str, Any]) -> dict[str, str]:
    return _workflow_step(
        "baseline",
        "简单对照测试",
        baseline.get("status", "pending"),
        baseline.get("detail") or _metric_detail(baseline),
    )


def _modeling_step(task: TaskRecord) -> dict[str, str]:
    return _workflow_step("modeling", "自动建模", _modeling_status(task), _modeling_detail(task))


def _modeling_status(task: TaskRecord) -> str:
    if task.last_run:
        return "completed"
    if task.status == TaskStatus.running:
        return "running"
    if task.status == TaskStatus.failed:
        return "failed"
    return "pending"


def _quality_step(quality_gates: list[Any]) -> dict[str, str]:
    return _workflow_step(
        "quality_review",
        "结果校验",
        quality_status(quality_gates),
        quality_detail(quality_gates),
    )


def _tuning_step(task: TaskRecord, next_improvement: dict[str, Any]) -> dict[str, str]:
    return _workflow_step(
        "iterative_tuning",
        "反复优化",
        _tuning_status(task, next_improvement),
        next_improvement.get("action") or "等待模型结果后决定是否需要下一轮优化。",
    )


def _tuning_status(task: TaskRecord, next_improvement: dict[str, Any]) -> str:
    if next_improvement.get("status") in {"proposed", "needs_human_or_retry"}:
        return "proposed"
    return "completed" if task.last_run else "pending"


def _final_report_step(task: TaskRecord) -> dict[str, str]:
    return _workflow_step(
        "final_report",
        "报告交付",
        "completed" if task.last_run else "pending",
        "基于真实结果文件生成报告，不用演示值补齐。",
    )


def _workflow_step(key: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _modeling_detail(task: TaskRecord) -> str:
    if task.last_run:
        return f"{task.last_run.best_model}: {task.last_run.metric_name}={task.last_run.metric_value:.6g}"
    if task.last_run_attempt and task.last_run_attempt.diagnosis_detail:
        return task.last_run_attempt.diagnosis_detail
    if task.status == TaskStatus.running:
        return "自动建模正在运行。"
    return "等待自动建模。"


def _metric_detail(payload: dict[str, Any]) -> str:
    if not baseline_completed(payload):
        return str(payload.get("detail") or "等待计算。")
    return f"{payload.get('label')}: {payload.get('metric_name')}={float(payload.get('metric_value')):.6g}"
