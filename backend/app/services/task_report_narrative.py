from __future__ import annotations

from typing import Any

from backend.app.models.task import DatasetProfile, FeatureImportanceEntry, TaskRecord
from backend.app.services.task_report_baseline import (
    compare_task_to_baseline,
    comparison_sentence,
)
from backend.app.services.task_report_formatting import (
    format_integer as _format_integer,
    format_metric_value as _format_metric_value,
)


def abstract_lines(
    task: TaskRecord,
    profile: DatasetProfile | None,
    agent_loop: dict[str, Any],
    feature_importance: list[FeatureImportanceEntry],
    candidate_count: int,
) -> list[str]:
    baseline = agent_loop.get("baseline") if isinstance(agent_loop, dict) else None
    return [
        _abstract_task_sentence(task, profile),
        _abstract_baseline_sentence(baseline),
        _abstract_model_sentence(task, baseline, candidate_count),
        _abstract_feature_sentence(feature_importance),
    ]


def run_conclusion(task: TaskRecord) -> str:
    if task.last_run:
        return "已完成，可基于本报告做模型验收"
    if task.last_run_attempt and task.last_run_attempt.diagnosis:
        return f"未完成，最后一次运行诊断为：{task.last_run_attempt.diagnosis}"
    if task.status.value == "running":
        return "仍在运行或等待修复，当前报告不是最终成功验收报告"
    return "未完成，尚无成功模型结果"


def conclusion_lines(
    task: TaskRecord,
    agent_loop: dict[str, Any],
    feature_importance: list[FeatureImportanceEntry],
) -> list[str]:
    if not task.last_run:
        return [
            "1. 当前任务还没有成功模型结果，不能给出最终模型优劣结论。",
            "2. 已有数据画像、简单对照或失败诊断仍可作为下一轮修复依据。",
            "3. 后续应先补齐结果摘要、候选模型对比和 AI 使用记录，再生成最终验收报告。",
        ]
    baseline = agent_loop.get("baseline") if isinstance(agent_loop, dict) else None
    comparison = compare_task_to_baseline(task, baseline)
    lines = [
        f"1. 本次自动建模已完成，最佳模型为 {task.last_run.best_model}，{task.last_run.metric_name} = {_format_metric_value(task.last_run.metric_value)}。",
    ]
    if comparison:
        lines.append(f"2. 与简单对照相比，{comparison_sentence(comparison)}")
    else:
        lines.append("2. 当前无法和简单对照做同口径比较，模型验收时应先补齐或确认简单对照指标。")
    if feature_importance:
        lines.append(f"3. 从解释性结果看，{format_top_features(feature_importance, limit=3)} 是当前最值得复核的关键字段。")
    else:
        lines.append("3. 当前解释性证据不足，建议补充模型原生特征重要性后再做业务验收。")
    raw_gates = agent_loop.get("quality_gates") if isinstance(agent_loop, dict) else []
    gates = raw_gates if isinstance(raw_gates, list) else []
    warnings = [gate for gate in gates if isinstance(gate, dict) and gate.get("status") in {"warning", "blocked"}]
    if warnings:
        lines.append(f"4. 仍有 {len(warnings)} 个结果检查问题需要处理，最优先项为：{warnings[0].get('title') or warnings[0].get('id')}。")
    else:
        lines.append("4. 当前没有记录阻塞级检查问题，可以进入人工复核和业务验收。")
    return lines


def next_step_lines(task: TaskRecord, feature_importance: list[FeatureImportanceEntry]) -> list[str]:
    if not task.last_run:
        return [
            "- 先重新运行并拿到完整结果摘要、候选模型对比和 AI 使用记录，再做模型验收。",
            "- 如果运行中断，优先处理运行日志中的具体异常，而不是只看候选模型分数。",
        ]
    lines = [
        "- 用独立验证集或时间外样本复核当前指标，避免只相信一次自动划分结果。",
        "- 对排名靠前的特征做业务复核，确认它们不是泄漏字段、文件路径、ID 或事后字段。",
    ]
    if not feature_importance:
        lines.append("- 补充模型给出的特征重要性，增强解释性。")
    return lines


def format_top_features(feature_importance: list[FeatureImportanceEntry], *, limit: int = 5) -> str:
    return "、".join(f"{item.feature}({item.importance:.3g})" for item in feature_importance[:limit])


def _abstract_task_sentence(task: TaskRecord, profile: DatasetProfile | None) -> str:
    dataset_text = (
        f"数据集包含 {_format_integer(profile.row_count)} 行、{_format_integer(profile.column_count)} 列"
        if profile is not None
        else "当前没有可读取的数据集画像"
    )
    target_text = f"目标列为 `{task.label_column}`" if task.label_column else "目标列尚未确认"
    task_text = f"任务类型为 {task.problem_type}" if task.problem_type else "任务类型尚未确认"
    return f"本报告围绕任务“{task.name}”整理自动建模全过程。{dataset_text}，{target_text}，{task_text}。"


def _abstract_baseline_sentence(baseline: Any) -> str:
    if isinstance(baseline, dict) and baseline.get("status") == "completed":
        return (
            "系统首先建立简单对照："
            f"{baseline.get('label') or baseline.get('method') or '简单对照'}，"
            f"{baseline.get('metric_name')} = {_format_metric_value(baseline.get('metric_value'))}。"
        )
    if isinstance(baseline, dict):
        return f"简单对照当前未完成：{baseline.get('detail') or baseline.get('status') or '暂无细节'}。"
    return "当前任务没有记录简单对照，因此报告无法给出最低参考线结论。"


def _abstract_model_sentence(task: TaskRecord, baseline: Any, candidate_count: int) -> str:
    if task.last_run:
        comparison = compare_task_to_baseline(task, baseline)
        comparison_text = f"；{comparison_sentence(comparison)}" if comparison else ""
        return (
            f"自动建模阶段共解析到 {_format_integer(candidate_count)} 个候选模型，"
            f"当前最优模型为 {task.last_run.best_model}，"
            f"{task.last_run.metric_name} = {_format_metric_value(task.last_run.metric_value)}{comparison_text}。"
        )
    return "自动建模阶段尚未产出成功模型，本报告只能作为数据诊断和过程复盘，不能作为最终模型验收。"


def _abstract_feature_sentence(feature_importance: list[FeatureImportanceEntry]) -> str:
    if feature_importance:
        return f"解释性分析中，排名靠前的特征包括：{format_top_features(feature_importance)}。"
    return "当前没有可用的特征重要性或稳定相关性结果，解释性部分需要在后续运行中补齐。"
