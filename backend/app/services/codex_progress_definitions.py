from __future__ import annotations

from typing import Any


PROGRESS_EVENTS_RELATIVE_PATH = "state/progress_events.jsonl"
PROGRESS_SCHEMA_VERSION = "ai4ml-progress-v1"
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

PROGRESS_EVENT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "workspace_initialized": {
        "status": "running",
        "step": "workspace_initialized",
        "title": "工作区已初始化",
        "summary": "AI4ML Codex-native 工作区已创建。",
    },
    "data_inspected": {
        "status": "running",
        "step": "dataset_analysis",
        "title": "数据已检查",
        "summary": "Codex 已完成数据结构检查。",
    },
    "plan_generated": {
        "status": "waiting_plan_approval",
        "step": "waiting_plan_approval",
        "title": "计划已生成",
        "summary": "Codex 已生成执行计划，等待用户确认。",
    },
    "plan_approved": {
        "status": "running",
        "step": "modeling",
        "title": "计划已确认",
        "summary": "用户已确认执行计划。",
    },
    "execution_started": {
        "status": "running",
        "step": "data_preparation",
        "title": "执行已开始",
        "summary": "Codex 已开始执行确认后的建模流程。",
    },
    "modeling_started": {
        "status": "running",
        "step": "modeling",
        "title": "建模已开始",
        "summary": "Codex 正在执行建模计划。",
    },
    "data_prepared": {
        "status": "running",
        "step": "data_preparation",
        "title": "数据准备完成",
        "summary": "训练前数据准备已完成。",
    },
    "baseline_completed": {
        "status": "running",
        "step": "baseline",
        "title": "基线已完成",
        "summary": "基线或对照结果已完成。",
    },
    "candidate_models_done": {
        "status": "running",
        "step": "candidate_models",
        "title": "候选模型完成",
        "summary": "候选模型或方法已完成。",
    },
    "validation_completed": {
        "status": "running",
        "step": "validation",
        "title": "验证完成",
        "summary": "模型验证或结果评估已完成。",
    },
    "artifacts_generated": {
        "status": "running",
        "step": "artifact_generation",
        "title": "产物已生成",
        "summary": "核心结果文件已生成。",
    },
    "final_review_completed": {
        "status": "running",
        "step": "final_review",
        "title": "最终复核完成",
        "summary": "最终结果复核已完成。",
    },
    "completed": {
        "status": "completed",
        "step": "completed",
        "title": "任务已完成",
        "summary": "Codex 建模任务已完成。",
    },
    "interrupted": {
        "status": "interrupted",
        "step": "interrupted",
        "title": "任务已中断",
        "summary": "Codex 运行已中断，可从当前工作区继续。",
    },
    "resume_requested": {
        "status": "running",
        "step": "resuming",
        "title": "恢复运行",
        "summary": "用户已要求从现有工作区继续运行。",
    },
    "failed": {
        "status": "failed",
        "step": "failed",
        "title": "任务失败",
        "summary": "Codex 任务未正常完成。",
    },
    "cancelled": {
        "status": "cancelled",
        "step": "cancelled",
        "title": "任务已取消",
        "summary": "用户已取消任务。",
    },
}


def progress_event_definition(event: object) -> dict[str, Any] | None:
    return PROGRESS_EVENT_DEFINITIONS.get(str(event or ""))


def progress_definition_value(definition: dict[str, Any] | None, key: str) -> str | None:
    if not definition:
        return None
    value = definition.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None
