from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import TaskRecord, TaskStatus, WorkflowStage
from backend.app.services.codex_artifact_state import (
    has_completed_codex_artifacts,
    has_failed_codex_acceptance,
    has_stop_and_report_codex_artifacts,
)
from backend.app.services.codex_common import (
    CODEX_ACTIVE_STATUSES,
    CODEX_FAILED_STATUSES,
    CODEX_WAITING_STATUSES,
)


def codex_status(task: TaskRecord, progress: dict[str, Any]) -> str:
    status = progress.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    if task.codex_status:
        return task.codex_status
    if task.status == TaskStatus.completed:
        return "completed"
    if task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return "waiting_plan_approval"
    if task.status == TaskStatus.running:
        return "running"
    return "not_started"


def codex_activity_text(
    task: TaskRecord,
    progress: dict[str, Any],
    codex_status_value: str,
    artifacts: dict[str, Any],
) -> str:
    summary = progress.get("summary")
    has_summary = isinstance(summary, str) and bool(summary.strip())
    if codex_status_value == "waiting_improvement_review":
        return summary.strip() if has_summary else "Codex 已生成改进决策方案，等待用户选择继续改进或按当前结果生成报告。"
    if codex_status_value in CODEX_WAITING_STATUSES:
        return summary.strip() if has_summary else "Codex 已生成计划，等待人工确认后开始训练和交付。"
    if has_stop_and_report_codex_artifacts(artifacts):
        return summary.strip() if has_summary else "Codex 已按用户选择停止继续改进，并生成当前结果报告。"
    if has_failed_codex_acceptance(artifacts):
        return "当前结果未达到已确认的成功阈值，请查看改进方案或失败诊断。"
    if codex_status_value == "completed":
        return summary.strip() if has_summary else "Codex 建模流程已完成，报告和预测入口已可查看。"
    if has_completed_codex_artifacts(artifacts):
        return "Codex 建模流程已完成，报告和预测入口已可查看。"
    if has_summary:
        return summary.strip()
    if codex_status_value in CODEX_ACTIVE_STATUSES:
        return "Codex 正在执行建模、验证和产物生成。"
    if codex_status_value == "interrupted" and task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return task.notes or "用户已暂停当前 Codex 运行，可继续执行。"
    if codex_status_value in CODEX_FAILED_STATUSES:
        return "Codex 任务未正常完成，请查看工作区日志和进度文件。"
    return task.notes or "Codex 任务尚未启动。"


def bootstrap_progress(workspace: Any, artifacts: dict[str, Any]) -> dict[str, Any]:
    has_workspace = isinstance(workspace, dict) and bool(workspace.get("path"))
    progress_file = artifacts.get("progress_file") if isinstance(artifacts.get("progress_file"), dict) else {}
    current_step = "dataset_analysis" if has_workspace else "environment_creation"
    if progress_file.get("exists") and not progress_file.get("readable"):
        detail = "Codex 进度文件存在但无法解析，当前没有可用的真实进度百分比。"
    elif has_workspace:
        detail = "Codex 已创建任务工作区，正在等待 output/progress.json 写入真实进度。"
    else:
        detail = "Codex 正在初始化运行环境，当前没有可用的真实进度百分比。"
    return {
        "status": "running",
        "current_step": current_step,
        "summary": detail,
        "steps": [
            {
                "id": "environment_creation",
                "title": "正在创建环境",
                "status": "completed" if has_workspace else "running",
                "detail": "初始化 Codex 运行环境和任务工作区。",
            },
            {
                "id": "dataset_analysis",
                "title": "正在分析数据集",
                "status": "running" if has_workspace else "pending",
                "detail": "读取数据结构、字段和任务描述，准备生成建模计划。",
            },
        ],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def codex_response_status(task: TaskRecord, codex_status_value: str, artifacts: dict[str, Any]) -> str:
    if has_stop_and_report_codex_artifacts(artifacts):
        return "completed"
    if codex_status_value in CODEX_WAITING_STATUSES:
        return "blocked"
    if codex_status_value == "interrupted" and task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return "blocked"
    if codex_status_value in CODEX_FAILED_STATUSES:
        return "failed"
    if has_failed_codex_acceptance(artifacts):
        return "blocked"
    if codex_status_value == "completed" or has_completed_codex_artifacts(artifacts) or task.status == TaskStatus.completed:
        return "completed"
    if codex_status_value in CODEX_ACTIVE_STATUSES:
        return "running"
    if task.status == TaskStatus.failed:
        return "failed"
    if task.status == TaskStatus.running:
        return "running"
    return "not_started"


def current_codex_stage(codex_status_value: str, progress: dict[str, Any], artifacts: dict[str, Any]) -> WorkflowStage | None:
    if has_stop_and_report_codex_artifacts(artifacts):
        return WorkflowStage.report_generation
    if codex_status_value == "waiting_improvement_review":
        return WorkflowStage.training_validation
    if has_failed_codex_acceptance(artifacts):
        return WorkflowStage.training_validation
    if codex_status_value in CODEX_WAITING_STATUSES:
        return WorkflowStage.data_analysis
    if codex_status_value == "completed" or has_completed_codex_artifacts(artifacts):
        return WorkflowStage.report_generation
    current_step = str(progress.get("current_step") or "").lower()
    if any(marker in current_step for marker in ("model", "train", "validation", "subagent")):
        return WorkflowStage.training_validation
    if any(marker in current_step for marker in ("plan", "analysis", "workspace")):
        return WorkflowStage.data_analysis
    if codex_status_value in CODEX_ACTIVE_STATUSES:
        return WorkflowStage.training_validation
    if codex_status_value == "interrupted" and artifacts.get("workspace"):
        return WorkflowStage.training_validation
    return None
