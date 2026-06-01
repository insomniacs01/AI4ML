from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import (
    HumanInteractionRequestStatus,
    PRIMARY_WORKFLOW_STAGES,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.codex_backend import codex_plan_text, codex_workspace_plan_path
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_artifacts import (
    collect_stage_artifacts_by_stage,
    read_run_log_excerpt,
)
from backend.app.services.task_workflow_tracking import _record_stage_selection_map


def update_codex_structured_metadata(task: TaskRecord) -> TaskRecord:
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    codex = structured.get("codex") if isinstance(structured.get("codex"), dict) else {}
    structured["executor_type"] = "codex"
    structured["codex"] = {
        **codex,
        "workspace_path": task.codex_workspace_path,
        "session_id": task.codex_session_id,
        "thread_id": task.codex_thread_id,
        "status": task.codex_status,
        "started_at": task.codex_started_at.isoformat() if task.codex_started_at else None,
        "finished_at": task.codex_finished_at.isoformat() if task.codex_finished_at else None,
    }
    task.structured_requirements = structured
    return task


def write_codex_plan_approved_progress(task: TaskRecord) -> None:
    if not task.codex_workspace_path:
        return
    progress = {
        "status": "running",
        "current_step": "modeling",
        "percent": 22,
        "summary": "计划已确认，Codex 正在执行建模、评估和报告生成。",
        "steps": [
            {
                "id": "environment_creation",
                "title": "正在创建环境",
                "status": "completed",
                "detail": "AI4ML 后端已创建 Codex-native 任务工作区和协议文件。",
            },
            {
                "id": "dataset_analysis",
                "title": "正在分析数据集",
                "status": "completed",
                "detail": "Codex 已读取数据结构、字段和任务描述。",
            },
            {
                "id": "plan_generation",
                "title": "生成工作计划",
                "status": "completed",
                "detail": "Codex 已写入 output/plan.md，用户已确认执行。",
            },
            {
                "id": "modeling",
                "title": "执行建模计划",
                "status": "running",
                "detail": "Codex 正在训练模型、验证指标、计算特征重要性并准备报告。",
            },
            {
                "id": "final_delivery",
                "title": "生成最终产物",
                "status": "pending",
                "detail": "等待 Codex 写入 metrics、report、model 和预测入口等产物。",
            },
        ],
    }
    write_codex_progress_file(task, progress)


def write_codex_resume_progress(task: TaskRecord) -> None:
    if not task.codex_workspace_path:
        return
    progress = {
        "status": "running",
        "current_step": "resuming",
        "percent": 82,
        "summary": "用户已要求继续运行，Codex 正在从现有工作区恢复任务。",
        "steps": [
            {
                "id": "resume_interrupted_task",
                "title": "恢复暂停任务",
                "status": "running",
                "detail": "正在读取已有 workspace、历史产物和进度，从中断处继续执行。",
            }
        ],
    }
    write_codex_progress_file(task, progress)


def write_codex_progress_file(task: TaskRecord, progress: dict[str, Any]) -> None:
    if not task.codex_workspace_path:
        return
    progress_path = Path(task.codex_workspace_path) / "output" / "progress.json"
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(f"{json.dumps(progress, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
    except OSError:
        return


def has_confirmed_codex_plan_request(task: TaskRecord, requests: list[object]) -> bool:
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    human_loop = structured.get("human_loop") if isinstance(structured.get("human_loop"), dict) else {}
    decision_history = human_loop.get("decision_history") if isinstance(human_loop.get("decision_history"), list) else []
    latest_decision = human_loop.get("latest_decision") if isinstance(human_loop.get("latest_decision"), dict) else None
    decisions = [item for item in [latest_decision, *decision_history] if isinstance(item, dict)]
    if any(
        item.get("request_type") == "codex_plan_approval"
        and item.get("action") in {"approve", "skip"}
        and item.get("resume_task") is not False
        for item in decisions
    ):
        return True
    for request in requests:
        if getattr(request, "version_id", None) != "codex-plan-approval":
            continue
        status_value = getattr(request, "status", "")
        status_text = str(status_value.value if hasattr(status_value, "value") else status_value)
        decision = getattr(request, "decision", None)
        if (
            status_text in {HumanInteractionRequestStatus.confirmed.value, HumanInteractionRequestStatus.skipped.value}
            and isinstance(decision, dict)
            and decision.get("action") in {"approve", "skip"}
        ):
            return True
    return False


def record_codex_running_stages(task: TaskRecord, team_access: TeamAccessContext) -> None:
    try:
        _record_stage_selection_map(
            task,
            team_access,
            stage_selection_map={},
            status_by_stage={
                WorkflowStage.requirement_analysis: WorkflowStageStatus.completed,
                WorkflowStage.data_analysis: WorkflowStageStatus.running,
                WorkflowStage.feature_engineering: WorkflowStageStatus.pending,
                WorkflowStage.model_selection: WorkflowStageStatus.pending,
                WorkflowStage.training_validation: WorkflowStageStatus.pending,
                WorkflowStage.report_generation: WorkflowStageStatus.pending,
            },
            summary_by_stage={
                WorkflowStage.requirement_analysis: "任务和数据已提交给 Codex。",
                WorkflowStage.data_analysis: "Codex 正在创建工作区、读取数据并生成计划。",
                WorkflowStage.feature_engineering: "等待计划确认后由 Codex 执行。",
                WorkflowStage.model_selection: "等待计划确认后由 Codex 执行。",
                WorkflowStage.training_validation: "等待计划确认后由 Codex 执行。",
                WorkflowStage.report_generation: "等待 Codex 完成后生成报告。",
            },
            artifact_refs=[task.dataset_path] if task.dataset_path else None,
        )
    except ConnectionError:
        return


def record_user_paused_stages(task: TaskRecord, team_access: TeamAccessContext) -> None:
    workspace_path = task.codex_workspace_path or (task.last_run_attempt.output_dir if task.last_run_attempt else None)
    try:
        _record_stage_selection_map(
            task,
            team_access,
            stage_selection_map={},
            status_by_stage={
                WorkflowStage.requirement_analysis: WorkflowStageStatus.completed,
                WorkflowStage.data_analysis: WorkflowStageStatus.completed,
                WorkflowStage.feature_engineering: WorkflowStageStatus.waiting_human,
                WorkflowStage.model_selection: WorkflowStageStatus.waiting_human,
                WorkflowStage.training_validation: WorkflowStageStatus.waiting_human,
                WorkflowStage.report_generation: WorkflowStageStatus.pending,
            },
            summary_by_stage={
                WorkflowStage.requirement_analysis: "任务和数据已提交给 Codex。",
                WorkflowStage.data_analysis: "Codex 工作区已创建，当前运行由用户暂停。",
                WorkflowStage.feature_engineering: "用户已暂停当前 Codex 运行，可继续执行。",
                WorkflowStage.model_selection: "用户已暂停当前 Codex 运行，可继续执行。",
                WorkflowStage.training_validation: "用户已暂停当前 Codex 运行，可继续执行。",
                WorkflowStage.report_generation: "等待继续运行后生成最终报告。",
            },
            artifact_refs=[workspace_path] if workspace_path else None,
        )
    except ConnectionError:
        return


def record_codex_status_stages(task: TaskRecord, team_access: TeamAccessContext, artifacts: dict) -> None:
    workspace_path = codex_stage_workspace_path(task)
    plan_path = codex_workspace_plan_path(task, get_settings())
    if is_human_waiting_task(task) and task.codex_status == "interrupted":
        record_user_paused_stages(task, team_access)
        return
    if is_human_waiting_task(task):
        record_codex_plan_gate_stages(task, team_access, workspace_path=workspace_path, plan_path=plan_path)
        return
    if task.status == TaskStatus.completed and task.last_run:
        record_completed_codex_stages(task, team_access, workspace_path=workspace_path)


def codex_stage_workspace_path(task: TaskRecord) -> str | None:
    return task.codex_workspace_path or (task.last_run_attempt.output_dir if task.last_run_attempt else None)


def is_human_waiting_task(task: TaskRecord) -> bool:
    return task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}


def record_codex_plan_gate_stages(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    workspace_path: str | None,
    plan_path: str | None,
) -> None:
    try:
        ensure_codex_plan_request(task, team_access, plan_path=plan_path)
        _record_stage_selection_map(
            task,
            team_access,
            stage_selection_map={},
            status_by_stage={
                WorkflowStage.requirement_analysis: WorkflowStageStatus.completed,
                WorkflowStage.data_analysis: WorkflowStageStatus.waiting_human,
                WorkflowStage.feature_engineering: WorkflowStageStatus.pending,
                WorkflowStage.model_selection: WorkflowStageStatus.pending,
                WorkflowStage.training_validation: WorkflowStageStatus.pending,
                WorkflowStage.report_generation: WorkflowStageStatus.pending,
            },
            summary_by_stage={
                WorkflowStage.requirement_analysis: "任务和数据已提交给 Codex。",
                WorkflowStage.data_analysis: "Codex 已生成计划，等待人工确认。",
                WorkflowStage.feature_engineering: "计划确认后继续。",
                WorkflowStage.model_selection: "计划确认后继续。",
                WorkflowStage.training_validation: "计划确认后继续。",
                WorkflowStage.report_generation: "等待最终报告。",
            },
            artifact_refs=[path for path in [workspace_path, plan_path] if path],
        )
    except ConnectionError:
        return


def record_completed_codex_stages(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    workspace_path: str | None,
) -> None:
    if not task.last_run:
        return
    try:
        _record_stage_selection_map(
            task,
            team_access,
            stage_selection_map={},
            status_by_stage={
                WorkflowStage.feature_engineering: WorkflowStageStatus.completed,
                WorkflowStage.model_selection: WorkflowStageStatus.completed,
                WorkflowStage.training_validation: WorkflowStageStatus.completed,
                WorkflowStage.report_generation: WorkflowStageStatus.completed,
            },
            summary_by_stage={
                WorkflowStage.feature_engineering: "Codex 已生成可查看代码和预测入口。",
                WorkflowStage.model_selection: f"Codex 已选择最终模型：{task.last_run.best_model}。",
                WorkflowStage.training_validation: f"Codex 验证完成：{task.last_run.metric_name} = {task.last_run.metric_value:.6g}。",
                WorkflowStage.report_generation: "Codex 已生成最终报告。",
            },
            artifact_refs=[workspace_path] if workspace_path else None,
            artifact_refs_by_stage=collect_stage_artifacts_by_stage(workspace_path),
            log_excerpt_by_stage={stage: read_run_log_excerpt(workspace_path) or "" for stage in PRIMARY_WORKFLOW_STAGES},
        )
    except ConnectionError:
        return


def ensure_codex_plan_request(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    plan_path: str | None = None,
) -> None:
    task_store = get_task_store()
    if plan_path is None:
        plan_path = codex_workspace_plan_path(task, get_settings())
    existing = task_store.list_human_requests(task.team_id, task.id, access_token=team_access.access_token)
    if any(
        request.version_id == "codex-plan-approval"
        and str(request.status.value if hasattr(request.status, "value") else request.status) in {"pending", "open"}
        for request in existing
    ):
        return
    if has_confirmed_codex_plan_request(task, existing):
        return
    request_payload = {
        "request_type": "codex_plan_approval",
        "title": "确认 Codex 建模计划",
        "summary": "Codex 已写入 output/plan.md。确认后将按该计划继续执行训练、验证和交付。",
        "suggested_action": "确认并继续 Codex 执行。",
        "plan_text": codex_plan_text(task, get_settings()),
        "artifact_paths": [path for path in [plan_path, task.codex_workspace_path] if path],
        "checkpoint_mode": "codex_plan_gate",
    }
    request = task_store.create_human_request(
        team_id=task.team_id,
        task_id=task.id,
        stage=WorkflowStage.data_analysis,
        requested_by=team_access.user.id,
        assigned_to=team_access.user.id,
        assignee_type="member",
        assignee_value=team_access.user.id,
        version_id="codex-plan-approval",
        payload=request_payload,
        access_token=team_access.access_token,
    )
    request.status = HumanInteractionRequestStatus.open
    task_store.update_human_request(request, access_token=team_access.access_token)
