from __future__ import annotations

from backend.app.models.task import TaskRecord
from backend.app.services.codex_progress_store import append_progress_event


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
