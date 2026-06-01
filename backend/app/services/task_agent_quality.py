from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_agent_baseline import baseline_completed, compare_metric, normalize_metric


def build_quality_gates(
    task: TaskRecord,
    baseline: Any,
    *,
    failure_note: str | None = None,
) -> list[dict[str, Any]]:
    gates = [_semantic_ready_gate(task), _baseline_ready_gate(baseline)]
    if failure_note:
        gates.append(_gate("run_failure", "运行失败诊断", "blocked", failure_note))
    if task.last_run:
        gates.extend(_successful_run_gates(task, baseline))
    elif task.status in {TaskStatus.failed, TaskStatus.running} and task.last_run_attempt:
        gates.append(_run_attempt_gate(task))
    return gates


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


def quality_status(gates: list[dict[str, Any]]) -> str:
    if not gates:
        return "pending"
    if any(gate.get("status") == "blocked" for gate in gates):
        return "blocked"
    if any(gate.get("status") == "warning" for gate in gates):
        return "warning"
    return "completed"


def quality_detail(gates: list[dict[str, Any]]) -> str:
    if not gates:
        return "等待简单对照和模型结果。"
    warning = next((gate for gate in gates if gate.get("status") in {"blocked", "warning"}), None)
    if warning:
        return str(warning.get("detail") or warning.get("title") or "存在待确认项。")
    return "结果检查均已通过。"


def _gate(gate_id: str, title: str, status: str, detail: str) -> dict[str, str]:
    return {"id": gate_id, "title": title, "status": status, "detail": detail}


def _semantic_ready_gate(task: TaskRecord) -> dict[str, str]:
    ready = bool(task.label_column and task.problem_type)
    return _gate(
        "semantic_ready",
        "任务语义可执行",
        "passed" if ready else "blocked",
        "目标列和问题类型已经确认。" if ready else "缺少目标列或问题类型。",
    )


def _baseline_ready_gate(baseline: Any) -> dict[str, str]:
    pending = isinstance(baseline, dict) and baseline.get("status") == "pending"
    status = "passed" if baseline_completed(baseline) else "warning" if pending else "blocked"
    detail = baseline.get("detail") if isinstance(baseline, dict) and baseline.get("detail") else "简单对照已完成。"
    return _gate("baseline_ready", "已建立简单对照", status, detail)


def _successful_run_gates(task: TaskRecord, baseline: Any) -> list[dict[str, str]]:
    gates = [
        _artifacts_complete_gate(task),
        _model_vs_baseline_gate(task, baseline),
        _candidate_models_gate(task),
    ]
    suspicious = _suspicious_score_detail(task, baseline)
    if suspicious:
        gates.append(_gate("leakage_review", "疑似泄漏或异常高分检查", "warning", suspicious))
    return gates


def _artifacts_complete_gate(task: TaskRecord) -> dict[str, str]:
    complete = bool(task.last_run and task.last_run.leaderboard and task.last_run.token_usage)
    return _gate(
        "artifacts_complete",
        "真实结果文件完整",
        "passed" if complete else "warning",
        "已读取结果摘要、候选模型对比和 AI 使用记录。" if complete else "运行成功，但候选模型对比或 AI 使用记录不完整。",
    )


def _candidate_models_gate(task: TaskRecord) -> dict[str, str]:
    candidate_count = len(task.last_run.leaderboard or []) if task.last_run else 0
    return _gate(
        "candidate_models",
        "候选模型数量",
        "passed" if candidate_count >= 2 else "warning",
        f"当前解析到 {candidate_count} 个候选模型。",
    )


def _run_attempt_gate(task: TaskRecord) -> dict[str, str]:
    return _gate(
        "run_attempt",
        "最近一次运行状态",
        "warning" if task.status == TaskStatus.running else "blocked",
        task.last_run_attempt.diagnosis_detail or task.notes or "本次运行没有成功结果文件。",
    )


def _model_vs_baseline_gate(task: TaskRecord, baseline: Any) -> dict[str, str]:
    if not task.last_run or not baseline_completed(baseline):
        return _gate("model_vs_baseline", "模型优于简单对照", "warning", "缺少模型结果或简单对照，无法比较。")
    comparison = compare_metric(
        task.last_run.metric_name,
        task.last_run.metric_value,
        str(baseline.get("metric_name") or ""),
        float(baseline.get("metric_value")),
    )
    if comparison is None:
        return _gate(
            "model_vs_baseline",
            "模型优于简单对照",
            "warning",
            f"模型指标 {task.last_run.metric_name} 与简单对照指标 {baseline.get('metric_name')} 不一致，无法直接比较。",
        )
    status = "passed" if comparison["better"] else "warning"
    return _gate(
        "model_vs_baseline",
        "模型优于简单对照",
        status,
        f"相对简单对照改善 {comparison['relative_delta']:.1%}。模型={comparison['model_value']:.6g}，简单对照={comparison['baseline_value']:.6g}。",
    )


def _suspicious_score_detail(task: TaskRecord, baseline: Any) -> str:
    if not task.last_run:
        return ""
    metric_key = normalize_metric(task.last_run.metric_name)
    value = task.last_run.metric_value
    if metric_key in {"accuracy", "balanced_accuracy", "f1", "roc_auc", "auc"} and value >= 0.995:
        return "分类指标接近满分，建议人工确认是否存在目标泄漏、ID 泄漏或事后字段。"
    if baseline_completed(baseline) and normalize_metric(str(baseline.get("metric_name"))) == metric_key:
        comparison = compare_metric(metric_key, value, metric_key, float(baseline["metric_value"]))
        if comparison and comparison["relative_delta"] >= 0.95:
            return "模型相对简单对照提升过大，建议检查数据划分和泄漏字段。"
    return ""
