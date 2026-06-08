from __future__ import annotations

from backend.app.models.task import RunSummary, WorkflowStage, WorkflowStageStatus
from backend.app.services.task_runtime_codex_stage_projection import (
    codex_improvement_gate_stage_projection,
    codex_plan_gate_stage_projection,
    codex_running_stage_projection,
    codex_user_paused_stage_projection,
    completed_codex_stage_projection,
)


def test_codex_running_stage_projection_uses_dataset_artifact() -> None:
    projection = codex_running_stage_projection("D:/datasets/train.csv")

    assert projection.status_by_stage[WorkflowStage.requirement_analysis] == WorkflowStageStatus.completed
    assert projection.status_by_stage[WorkflowStage.data_analysis] == WorkflowStageStatus.running
    assert projection.status_by_stage[WorkflowStage.training_validation] == WorkflowStageStatus.pending
    assert projection.summary_by_stage[WorkflowStage.data_analysis] == "Codex 正在创建工作区、读取数据并生成计划。"
    assert projection.artifact_refs == ["D:/datasets/train.csv"]


def test_codex_user_paused_stage_projection_marks_modeling_stages_waiting() -> None:
    projection = codex_user_paused_stage_projection("D:/workspaces/task-1")

    assert projection.status_by_stage[WorkflowStage.data_analysis] == WorkflowStageStatus.completed
    assert projection.status_by_stage[WorkflowStage.feature_engineering] == WorkflowStageStatus.waiting_human
    assert projection.status_by_stage[WorkflowStage.model_selection] == WorkflowStageStatus.waiting_human
    assert projection.status_by_stage[WorkflowStage.training_validation] == WorkflowStageStatus.waiting_human
    assert projection.summary_by_stage[WorkflowStage.report_generation] == "等待继续运行后生成最终报告。"
    assert projection.artifact_refs == ["D:/workspaces/task-1"]


def test_codex_gate_stage_projections_filter_empty_artifact_paths() -> None:
    plan_projection = codex_plan_gate_stage_projection("D:/workspaces/task-1", None)
    improvement_projection = codex_improvement_gate_stage_projection(None, "D:/workspaces/task-1/output/improvement.md")

    assert plan_projection.status_by_stage[WorkflowStage.data_analysis] == WorkflowStageStatus.waiting_human
    assert plan_projection.status_by_stage[WorkflowStage.feature_engineering] == WorkflowStageStatus.pending
    assert plan_projection.artifact_refs == ["D:/workspaces/task-1"]

    assert improvement_projection.status_by_stage[WorkflowStage.training_validation] == WorkflowStageStatus.waiting_human
    assert improvement_projection.status_by_stage[WorkflowStage.report_generation] == WorkflowStageStatus.pending
    assert improvement_projection.artifact_refs == ["D:/workspaces/task-1/output/improvement.md"]


def test_completed_codex_stage_projection_uses_run_summary_artifacts_and_log_excerpt() -> None:
    projection = completed_codex_stage_projection(
        RunSummary(best_model="ridge", metric_name="mae", metric_value=2.0, output_dir="D:/workspaces/task-1"),
        workspace_path="D:/workspaces/task-1",
        artifact_refs_by_stage={WorkflowStage.training_validation: ["D:/workspaces/task-1/output/metrics.json"]},
        log_excerpt="run log",
    )

    assert projection.status_by_stage[WorkflowStage.report_generation] == WorkflowStageStatus.completed
    assert projection.summary_by_stage[WorkflowStage.model_selection] == "Codex 已选择最终模型：ridge。"
    assert projection.summary_by_stage[WorkflowStage.training_validation] == "Codex 验证完成：mae = 2。"
    assert projection.artifact_refs == ["D:/workspaces/task-1"]
    assert projection.artifact_refs_by_stage == {
        WorkflowStage.training_validation: ["D:/workspaces/task-1/output/metrics.json"]
    }
    assert projection.log_excerpt_by_stage is not None
    assert projection.log_excerpt_by_stage[WorkflowStage.report_generation] == "run log"
