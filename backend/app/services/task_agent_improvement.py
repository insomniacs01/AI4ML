from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord


def build_next_improvement(task: TaskRecord, quality_gates: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [gate for gate in quality_gates if gate.get("status") == "blocked"]
    warnings = [gate for gate in quality_gates if gate.get("status") == "warning"]
    if blocking:
        first = blocking[0]
        return {
            "status": "needs_human_or_retry",
            "reason_code": first.get("id"),
            "hypothesis": "阻塞项需要先被修复，否则继续自动调优没有意义。",
            "action": "处理阻塞项后从相关阶段重跑。",
            "detail": first.get("detail"),
            "changed_config": {"rerun_from_stage": "data_analysis"},
        }
    if task.last_run and any(gate.get("id") == "model_vs_baseline" and gate.get("status") == "warning" for gate in warnings):
        return {
            "status": "proposed",
            "reason_code": "model_vs_baseline",
            "hypothesis": "当前模型没有稳定超过简单对照，需要增加搜索或复核目标列。",
            "action": "先人工确认目标列和指标，再增加候选模型/搜索轮次后重跑训练验证阶段。",
            "detail": "模型效果未达到简单对照改善门槛。",
            "changed_config": {"rerun_from_stage": "training_validation", "increase_candidate_models": True},
        }
    if task.last_run and any(gate.get("id") == "leakage_review" for gate in warnings):
        return {
            "status": "proposed",
            "reason_code": "leakage_review",
            "hypothesis": "指标异常高可能来自泄漏字段，移除疑似字段后应重新验证。",
            "action": "人工确认可疑特征，必要时删除泄漏列并从数据分析阶段重跑。",
            "detail": next((gate.get("detail") for gate in warnings if gate.get("id") == "leakage_review"), ""),
            "changed_config": {"rerun_from_stage": "data_analysis", "review_leakage_columns": True},
        }
    if task.last_run and len(task.last_run.leaderboard or []) < 2:
        return {
            "status": "proposed",
            "reason_code": "candidate_models",
            "hypothesis": "候选模型太少，模型选择稳定性不足。",
            "action": "增加候选模型数量或运行轮次后重新训练验证。",
            "detail": "候选模型对比不足 2 个。",
            "changed_config": {"rerun_from_stage": "training_validation", "min_candidate_models": 3},
        }
    return {
        "status": "not_needed" if task.last_run else "pending",
        "reason_code": None,
        "hypothesis": "当前没有必须立即优化的问题。",
        "action": "进入报告生成和人工验收。",
        "detail": "如果业务目标更高，可手动发起下一轮调优。",
        "changed_config": {},
    }
