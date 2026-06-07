from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.codex_backend import codex_workspace_plan_path
from backend.app.services.codex_progress_store import append_progress_event
from backend.app.services.task_artifacts import (
    collect_stage_artifacts_by_stage,
    read_run_log_excerpt,
)
from backend.app.services.task_codex_human_requests import ensure_codex_improvement_request, ensure_codex_plan_request
from backend.app.services.task_codex_improvement_review import (
    codex_stage_workspace_path,
    codex_workspace_improvement_plan_path,
    has_codex_improvement_review,
)
from backend.app.services.task_workflow_tracking import _record_stage_selection_map


def write_codex_plan_approved_progress(task: TaskRecord) -> None:
    if not task.codex_workspace_path:
        return
    append_progress_event(
        task.codex_workspace_path,
        "plan_approved",
        actor="ai4ml_backend",
        status="running",
        step="modeling",
        message="计划已确认，Codex 正在执行建模、评估和报告生成。",
        evidence=["output/plan.md"],
        steps=[
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
    )


def write_codex_resume_progress(task: TaskRecord) -> None:
    if not task.codex_workspace_path:
        return
    append_progress_event(
        task.codex_workspace_path,
        "resume_requested",
        actor="ai4ml_backend",
        status="running",
        step="resuming",
        message="用户已要求继续运行，Codex 正在从现有工作区恢复任务。",
        evidence=["output/progress.json"],
        steps=[
            {
                "id": "resume_interrupted_task",
                "title": "恢复暂停任务",
                "status": "running",
                "detail": "正在读取已有 workspace、历史产物和进度，从中断处继续执行。",
            }
        ],
    )


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
    improvement_plan_path = codex_workspace_improvement_plan_path(task, artifacts)
    if is_human_waiting_task(task) and task.codex_status == "interrupted":
        record_user_paused_stages(task, team_access)
        return
    if is_human_waiting_task(task) and has_codex_improvement_review(artifacts):
        record_codex_improvement_gate_stages(
            task,
            team_access,
            artifacts=artifacts,
            workspace_path=workspace_path,
            improvement_plan_path=improvement_plan_path,
        )
        return
    if is_human_waiting_task(task):
        record_codex_plan_gate_stages(task, team_access, workspace_path=workspace_path, plan_path=plan_path)
        return
    if task.status == TaskStatus.completed and task.last_run:
        record_completed_codex_stages(task, team_access, workspace_path=workspace_path)


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


def record_codex_improvement_gate_stages(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    artifacts: dict,
    workspace_path: str | None,
    improvement_plan_path: str | None,
) -> None:
    try:
        ensure_codex_improvement_request(
            task,
            team_access,
            artifacts=artifacts,
            improvement_plan_path=improvement_plan_path,
        )
        _record_stage_selection_map(
            task,
            team_access,
            stage_selection_map={},
            status_by_stage={
                WorkflowStage.requirement_analysis: WorkflowStageStatus.completed,
                WorkflowStage.data_analysis: WorkflowStageStatus.completed,
                WorkflowStage.feature_engineering: WorkflowStageStatus.completed,
                WorkflowStage.model_selection: WorkflowStageStatus.completed,
                WorkflowStage.training_validation: WorkflowStageStatus.waiting_human,
                WorkflowStage.report_generation: WorkflowStageStatus.pending,
            },
            summary_by_stage={
                WorkflowStage.requirement_analysis: "任务和数据已提交给 Codex。",
                WorkflowStage.data_analysis: "Codex 已完成数据理解和计划确认。",
                WorkflowStage.feature_engineering: "Codex 已完成当前策略内的数据处理或核心分析。",
                WorkflowStage.model_selection: "Codex 已完成当前策略内的候选模型或方法比较。",
                WorkflowStage.training_validation: "当前结果未满足验收规则，等待用户选择继续改进或停止并生成报告。",
                WorkflowStage.report_generation: "等待用户确认后生成最终报告。",
            },
            artifact_refs=[path for path in [workspace_path, improvement_plan_path] if path],
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
