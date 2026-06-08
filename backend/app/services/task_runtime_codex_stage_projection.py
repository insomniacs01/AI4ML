from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.task import PRIMARY_WORKFLOW_STAGES, RunSummary, WorkflowStage, WorkflowStageStatus


@dataclass(frozen=True)
class CodexStageProjection:
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus]
    summary_by_stage: dict[WorkflowStage, str]
    artifact_refs: list[str] | dict | None = None
    artifact_refs_by_stage: dict[WorkflowStage, list[str] | dict] | None = None
    log_excerpt_by_stage: dict[WorkflowStage, str] | None = None


def codex_running_stage_projection(dataset_path: str | None) -> CodexStageProjection:
    return CodexStageProjection(
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
        artifact_refs=_artifact_refs(dataset_path),
    )


def codex_user_paused_stage_projection(workspace_path: str | None) -> CodexStageProjection:
    return CodexStageProjection(
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
        artifact_refs=_artifact_refs(workspace_path),
    )


def codex_plan_gate_stage_projection(workspace_path: str | None, plan_path: str | None) -> CodexStageProjection:
    return CodexStageProjection(
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
        artifact_refs=_artifact_refs(workspace_path, plan_path),
    )


def codex_improvement_gate_stage_projection(
    workspace_path: str | None,
    improvement_plan_path: str | None,
) -> CodexStageProjection:
    return CodexStageProjection(
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
        artifact_refs=_artifact_refs(workspace_path, improvement_plan_path),
    )


def completed_codex_stage_projection(
    last_run: RunSummary,
    *,
    workspace_path: str | None,
    artifact_refs_by_stage: dict[WorkflowStage, list[str] | dict] | None,
    log_excerpt: str | None,
) -> CodexStageProjection:
    return CodexStageProjection(
        status_by_stage={
            WorkflowStage.feature_engineering: WorkflowStageStatus.completed,
            WorkflowStage.model_selection: WorkflowStageStatus.completed,
            WorkflowStage.training_validation: WorkflowStageStatus.completed,
            WorkflowStage.report_generation: WorkflowStageStatus.completed,
        },
        summary_by_stage={
            WorkflowStage.feature_engineering: "Codex 已生成可查看代码和预测入口。",
            WorkflowStage.model_selection: f"Codex 已选择最终模型：{last_run.best_model}。",
            WorkflowStage.training_validation: f"Codex 验证完成：{last_run.metric_name} = {last_run.metric_value:.6g}。",
            WorkflowStage.report_generation: "Codex 已生成最终报告。",
        },
        artifact_refs=_artifact_refs(workspace_path),
        artifact_refs_by_stage=artifact_refs_by_stage,
        log_excerpt_by_stage={stage: log_excerpt or "" for stage in PRIMARY_WORKFLOW_STAGES},
    )


def _artifact_refs(*paths: str | None) -> list[str] | None:
    refs = [path for path in paths if path]
    return refs or None
