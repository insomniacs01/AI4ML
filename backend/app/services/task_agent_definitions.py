from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    WorkflowStage,
    normalize_workflow_stage,
)


AGENT_DEFINITIONS: dict[WorkflowStage, dict[str, Any]] = {
    WorkflowStage.requirement_analysis: {
        "name": "需求理解",
        "role": "理解任务",
        "short_role": "需求",
        "description": "理解业务目标，整理任务约束与输出要求。",
        "x": 10,
        "y": 45,
    },
    WorkflowStage.data_analysis: {
        "name": "数据检查",
        "role": "检查数据",
        "short_role": "数据",
        "description": "检查 CSV 字段、目标列、缺失值与任务类型。",
        "x": 27,
        "y": 24,
    },
    WorkflowStage.feature_engineering: {
        "name": "数据处理",
        "role": "准备训练数据",
        "short_role": "特征",
        "description": "生成数据处理与训练前特征逻辑。",
        "x": 45,
        "y": 57,
    },
    WorkflowStage.model_selection: {
        "name": "模型准备",
        "role": "选择候选模型",
        "short_role": "模型",
        "description": "选择候选模型并组织比较方案。",
        "x": 62,
        "y": 30,
    },
    WorkflowStage.training_validation: {
        "name": "训练验证",
        "role": "训练并检查结果",
        "short_role": "训练",
        "description": "执行训练、验证、错误修复和结果记录。",
        "x": 76,
        "y": 62,
    },
    WorkflowStage.report_generation: {
        "name": "报告整理",
        "role": "生成报告",
        "short_role": "报告",
        "description": "汇总指标、生成文件、报告快照和试算入口。",
        "x": 90,
        "y": 44,
    },
}

MESSAGE_TYPE_LABELS = {
    "coordination": "步骤安排",
    "handoff": "阶段交接",
    "acknowledgement": "接收确认",
    "blocker": "阻塞通知",
    "human_review": "人工确认",
    "result": "结果广播",
}


def agent_definition(stage: WorkflowStage | str) -> dict[str, Any]:
    return AGENT_DEFINITIONS[normalize_workflow_stage(stage)]


def agent_runtime_spec_for_stage(stage: WorkflowStage | str) -> dict[str, Any]:
    normalized_stage = normalize_workflow_stage(stage)
    definition = agent_definition(normalized_stage)
    return {
        "agent_id": normalized_stage.value,
        "stage": normalized_stage,
        "name": definition["name"],
        "role": definition["role"],
        "short_role": definition["short_role"],
        "description": definition["description"],
        "x": definition["x"],
        "y": definition["y"],
}


def next_primary_stage(stage: WorkflowStage) -> WorkflowStage | None:
    try:
        index = PRIMARY_WORKFLOW_STAGES.index(stage)
    except ValueError:
        return None
    next_index = index + 1
    return PRIMARY_WORKFLOW_STAGES[next_index] if next_index < len(PRIMARY_WORKFLOW_STAGES) else None
