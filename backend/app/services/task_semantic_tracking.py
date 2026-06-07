from __future__ import annotations

from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import (
    TaskRecord,
    TaskSemanticUpdateRequest,
    TaskStageRoutingRecord,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.task_workflow_tracking import (
    _record_stage_selection_map,
    _record_workflow_stage,
)


SEMANTIC_UPDATE_PENDING_SUMMARIES = {
    WorkflowStage.feature_engineering: "任务语义已人工修正，等待下一次 Codex 运行重新生成特征与训练代码。",
    WorkflowStage.model_selection: "任务语义已人工修正，等待下一次 Codex 运行重新选择候选模型。",
    WorkflowStage.training_validation: "任务语义已人工修正，等待下一次 Codex 运行重新训练验证。",
    WorkflowStage.report_generation: "任务语义已人工修正，等待新的真实运行结果后生成报告。",
}


def record_human_semantic_update_stages(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    payload: TaskSemanticUpdateRequest,
    stage_selection_map: dict[str, TaskStageRoutingRecord],
) -> None:
    artifact_refs = [task.dataset_path] if task.dataset_path else None
    _record_workflow_stage(
        task,
        team_access,
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.completed,
        summary=(
            f"用户已人工修正任务语义：目标列 {task.label_column}，"
            f"任务类型 {task.problem_type}，指标 {payload.metric_name.strip().lower()}。"
        ),
        selection=stage_selection_map.get(WorkflowStage.data_analysis.value),
        artifact_refs=artifact_refs,
        log_excerpt=payload.correction_note,
    )
    _record_stage_selection_map(
        task,
        team_access,
        stage_selection_map=stage_selection_map,
        status_by_stage={
            WorkflowStage.feature_engineering: WorkflowStageStatus.pending,
            WorkflowStage.model_selection: WorkflowStageStatus.pending,
            WorkflowStage.training_validation: WorkflowStageStatus.pending,
            WorkflowStage.report_generation: WorkflowStageStatus.pending,
        },
        summary_by_stage=SEMANTIC_UPDATE_PENDING_SUMMARIES,
        artifact_refs=artifact_refs,
    )
