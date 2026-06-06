from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import (
    TaskRecord,
    TaskRunProgressArtifactSummary,
    TaskRunProgressEvent,
    TaskRunProgressInsight,
    TaskRunProgressLeaderboardRow,
    TaskRunProgressResponse,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.codex_common import (
    CODEX_ACTIVE_STATUSES,
    CODEX_FAILED_STATUSES,
    CODEX_WAITING_STATUSES,
    latest_workspace_update,
    read_text,
    workspace_path_from_artifacts,
)
from backend.app.services.codex_metrics import (
    leaderboard_from_metrics,
    primary_metric,
    selected_model_metrics,
)
from backend.app.services.codex_overview import build_codex_overview_from_artifacts
from backend.app.services.codex_usage import token_usage_from_artifacts


def build_codex_run_progress_response(task: TaskRecord, artifacts: dict[str, Any]) -> TaskRunProgressResponse:
    workspace = artifacts.get("workspace")
    progress = artifacts.get("progress") if isinstance(artifacts.get("progress"), dict) else {}
    if not progress and task.status == TaskStatus.running:
        progress = _bootstrap_progress(workspace)
    metrics = artifacts.get("metrics") if isinstance(artifacts.get("metrics"), dict) else {}
    workspace_path = workspace_path_from_artifacts(artifacts)
    status = codex_status(task, progress)
    response_status = _progress_status(task, status, artifacts)
    current_stage = _current_stage(status, progress, artifacts)
    current_activity = codex_activity_text(task, progress, status, artifacts)
    percent = _progress_percent(task, progress, status, artifacts)
    latest_log_lines = _latest_codex_log_lines(Path(workspace_path)) if workspace_path else []
    leaderboard = leaderboard_from_metrics(metrics)
    overview = build_codex_overview_from_artifacts(artifacts)
    summary = _artifact_summary(artifacts, metrics, leaderboard, overview)
    insights = _codex_insights(progress, artifacts)
    events = _codex_events(progress, artifacts)

    return TaskRunProgressResponse(
        task=task,
        output_dir=workspace_path,
        status=response_status,
        progress_percent=percent,
        current_stage=current_stage,
        current_activity=current_activity,
        observer_status="Codex",
        observer_detail=current_activity,
        observer_stage=current_stage,
        last_log_at=latest_workspace_update(Path(workspace_path)) if workspace_path else None,
        artifacts=summary,
        latest_log_lines=latest_log_lines,
        events=events,
        insights=insights,
        leaderboard=leaderboard,
        current_model=summary.best_model,
        completed_model_count=len(leaderboard) if leaderboard else None,
        total_model_count=len(leaderboard) if leaderboard else None,
        latest_validation_score=summary.metric_value,
        telemetry_note="Progress is read from the Codex-native AI4ML workspace.",
        codex_raw_progress=progress,
        codex_raw_steps=progress.get("steps") if isinstance(progress.get("steps"), list) else [],
        codex_workspace_path=workspace_path,
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
    if codex_status_value == "completed":
        return summary.strip() if has_summary else "Codex 建模流程已完成，报告和预测入口已可查看。"
    if has_completed_codex_artifacts(artifacts):
        return "Codex 建模流程已完成，报告和预测入口已可查看。"
    if has_summary:
        return summary.strip()
    if codex_status_value == "waiting_improvement_review":
        return "Codex 已生成改进决策方案，等待用户选择继续改进或停止并生成报告。"
    if codex_status_value in CODEX_WAITING_STATUSES:
        return "Codex 已生成计划，等待人工确认后开始训练和交付。"
    if codex_status_value in CODEX_ACTIVE_STATUSES:
        return "Codex 正在执行建模、验证和产物生成。"
    if codex_status_value == "interrupted" and task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return task.notes or "用户已暂停当前 Codex 运行，可继续执行。"
    if codex_status_value in CODEX_FAILED_STATUSES:
        return "Codex 任务未正常完成，请查看工作区日志和进度文件。"
    return task.notes or "Codex 任务尚未启动。"


def has_completed_codex_artifacts(artifacts: dict[str, Any]) -> bool:
    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    predict = artifacts.get("predict") if isinstance(artifacts.get("predict"), dict) else {}
    return bool(report.get("exists") and predict.get("exists") and isinstance(artifacts.get("metrics"), dict))


def _bootstrap_progress(workspace: Any) -> dict[str, Any]:
    has_workspace = isinstance(workspace, dict) and bool(workspace.get("path"))
    current_step = "dataset_analysis" if has_workspace else "environment_creation"
    title = "正在分析数据集" if has_workspace else "正在创建环境"
    detail = "Codex 已创建任务工作区，正在读取数据并生成计划。" if has_workspace else "Codex 正在初始化运行环境并准备任务工作区。"
    return {
        "status": "running",
        "current_step": current_step,
        "summary": detail,
        "percent": 18 if has_workspace else 8,
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


def _progress_status(task: TaskRecord, codex_status_value: str, artifacts: dict[str, Any]) -> str:
    if codex_status_value in CODEX_WAITING_STATUSES:
        return "blocked"
    if codex_status_value == "completed" or has_completed_codex_artifacts(artifacts) or task.status == TaskStatus.completed:
        return "completed"
    if codex_status_value in CODEX_ACTIVE_STATUSES:
        return "running"
    if codex_status_value == "interrupted" and task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return "blocked"
    if codex_status_value in CODEX_FAILED_STATUSES or task.status == TaskStatus.failed:
        return "failed"
    if task.status == TaskStatus.running:
        return "running"
    return "not_started"


def _current_stage(codex_status_value: str, progress: dict[str, Any], artifacts: dict[str, Any]) -> WorkflowStage | None:
    if codex_status_value == "waiting_improvement_review":
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


def _progress_percent(
    task: TaskRecord,
    progress: dict[str, Any],
    codex_status_value: str,
    artifacts: dict[str, Any],
) -> int:
    raw_percent = progress.get("percent") or progress.get("progress_percent")
    try:
        percent = int(raw_percent)
    except (TypeError, ValueError):
        percent = 0
    if codex_status_value == "completed" or task.status == TaskStatus.completed or has_completed_codex_artifacts(artifacts):
        return 100
    step_percent = _progress_percent_from_steps(progress.get("steps"))
    percent = max(percent, step_percent)
    if task.status in {TaskStatus.failed, TaskStatus.cancelled}:
        return min(99, max(0, percent))
    if codex_status_value == "interrupted" and task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return 25
    if codex_status_value in CODEX_FAILED_STATUSES:
        return min(99, max(0, percent))
    if percent:
        return max(0, min(99, percent))
    if codex_status_value in CODEX_WAITING_STATUSES:
        return 25
    if codex_status_value in CODEX_ACTIVE_STATUSES:
        return 65
    return 0


def _progress_percent_from_steps(steps: Any) -> int:
    if not isinstance(steps, list) or not steps:
        return 0

    completed_weight = 0.0
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = str(step.get("status") or "").strip().lower()
        if status in {"completed", "done", "success"}:
            completed_weight += 1.0
        elif status in {"running", "in_progress", "executing"}:
            completed_weight += 0.55
        elif status in {"waiting", "waiting_human", "waiting_plan_approval", "plan_ready", "waiting_improvement_review", "blocked"}:
            completed_weight += 0.35

    if completed_weight <= 0:
        return 0
    return int(round((completed_weight / len(steps)) * 100))


def _artifact_summary(
    artifacts: dict[str, Any],
    metrics: dict[str, Any],
    leaderboard: list[TaskRunProgressLeaderboardRow],
    overview: dict[str, Any] | None = None,
) -> TaskRunProgressArtifactSummary:
    workspace_path = workspace_path_from_artifacts(artifacts)
    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    predict = artifacts.get("predict") if isinstance(artifacts.get("predict"), dict) else {}
    overview_file = artifacts.get("overview_file") if isinstance(artifacts.get("overview_file"), dict) else {}
    token_usage = token_usage_from_artifacts(artifacts)
    selected = selected_model_metrics(metrics)
    metric_name, metric_value = primary_metric(selected, metrics)
    return TaskRunProgressArtifactSummary(
        has_run_summary=bool(metrics),
        has_leaderboard=bool(leaderboard),
        has_token_usage=token_usage is not None,
        has_generated_code=bool(predict.get("exists")),
        has_overview=bool(overview),
        run_summary_path=str(Path(workspace_path) / "output" / "metrics.json") if workspace_path and metrics else None,
        leaderboard_path=str(Path(workspace_path) / "output" / "metrics.json") if workspace_path and leaderboard else None,
        token_usage_path=str(Path(workspace_path) / "output" / "token_usage.json") if workspace_path and token_usage else None,
        generated_code_path=str(predict.get("path")) if predict.get("exists") else None,
        overview_path=str(overview_file.get("path")) if overview_file.get("exists") else None,
        best_model=str(selected.get("name")) if selected.get("name") else None,
        metric_name=metric_name,
        metric_value=metric_value,
        validation_score=metric_value,
        candidate_model_count=len(leaderboard) if leaderboard else None,
        error_log_path=str(Path(workspace_path) / "output" / "progress.json") if workspace_path else None,
        error_log_name="progress.json" if workspace_path else None,
    )


def _codex_events(progress: dict[str, Any], artifacts: dict[str, Any]) -> list[TaskRunProgressEvent]:
    events: list[TaskRunProgressEvent] = []
    for step in progress.get("steps") if isinstance(progress.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        title = str(step.get("title") or step.get("id") or "Codex step")
        detail = str(step.get("detail") or "")
        events.append(
            TaskRunProgressEvent(
                stage=_stage_from_step(str(step.get("id") or title)),
                event_type=str(step.get("status") or "codex_step"),
                message=f"{title}: {detail}" if detail else title,
                source="codex_progress",
            )
        )
    if not events and artifacts.get("plan"):
        events.append(
            TaskRunProgressEvent(
                stage=WorkflowStage.data_analysis,
                event_type="plan_ready",
                message="Codex 已写入 output/plan.md。",
                source="codex_workspace",
            )
        )
    return events[-80:]


def _codex_insights(progress: dict[str, Any], artifacts: dict[str, Any]) -> list[TaskRunProgressInsight]:
    status_value = str(progress.get("status") or "")
    severity = "success" if status_value == "completed" else "warning" if status_value in CODEX_WAITING_STATUSES else "info"
    detail = str(progress.get("summary") or "")
    if not detail and artifacts.get("plan"):
        detail = "计划文件已生成，等待确认。"
    if not detail:
        detail = "等待 Codex 写入进度文件。"
    return [
        TaskRunProgressInsight(
            stage=_current_stage(status_value, progress, artifacts),
            event_type=f"codex_{status_value or 'unknown'}",
            headline="Codex 状态",
            detail=detail,
            evidence=workspace_path_from_artifacts(artifacts),
            source="codex_progress",
            severity=severity,
        )
    ]


def _stage_from_step(step_id: str) -> WorkflowStage:
    lowered = step_id.lower()
    if "report" in lowered or "artifact" in lowered or "final" in lowered:
        return WorkflowStage.report_generation
    if "model" in lowered or "validation" in lowered or "train" in lowered:
        return WorkflowStage.training_validation
    if "feature" in lowered:
        return WorkflowStage.feature_engineering
    return WorkflowStage.data_analysis


def _latest_codex_log_lines(workspace_path: Path) -> list[str]:
    candidates = [
        workspace_path / "output" / "progress.json",
        workspace_path / "output" / "report.md",
        workspace_path / "output" / "metrics.json",
    ]
    lines: list[str] = []
    for path in candidates:
        text = read_text(path)
        if text:
            lines.extend(f"{path.name}: {line}" for line in text.splitlines()[-20:])
    return lines[-80:]
