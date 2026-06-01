from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetProfile, FeatureImportanceEntry, TaskRecord
from backend.app.services.task_artifacts import build_run_artifact_index
from backend.app.services.task_report_formatting import (
    artifact_status as _artifact_status,
    escape_table_cell as _escape_table_cell,
    format_integer as _format_integer,
    format_metric_value as _format_metric_value,
    markdown_table as _markdown_table,
    path_text as _path_text,
)
from backend.app.services.task_report_dataset import (
    dataset_overview_lines as _dataset_overview_lines,
    field_quality_table_lines as _field_quality_table_lines,
    task_background_lines as _task_background_lines,
)
from backend.app.services.task_report_agent_loop import (
    agent_loop as _agent_loop,
    baseline_experiment_lines as _baseline_experiment_lines,
    checklist_report_lines as _checklist_report_lines,
    compare_task_to_baseline as _compare_task_to_baseline,
    comparison_sentence as _comparison_sentence,
    quality_gate_report_lines as _quality_gate_report_lines,
    stop_condition_report_lines as _stop_condition_report_lines,
    tuning_attempt_report_lines as _tuning_attempt_report_lines,
    workflow_report_lines as _workflow_report_lines,
)
from backend.app.services.task_report_target_profile import build_target_profile


def build_report_markdown(
    *,
    task: TaskRecord,
    generated_at: datetime,
    dataset_profile: DatasetProfile | None,
    feature_importance: list[FeatureImportanceEntry],
    result_summary: list[str],
    data_quality_notes: list[str],
    limitation_notes: list[str],
    relationship_notes: list[str],
    using_artifact_importance: bool,
) -> str:
    agent_loop = _agent_loop(task)
    target_profile = build_target_profile(task, dataset_profile)
    artifact_index = build_run_artifact_index(task, prefer_success=True)
    primary_metric = _primary_metric_text(task)
    candidate_count = len(task.last_run.leaderboard or []) if task.last_run else 0
    lines = [
        f"# {task.name} 自动建模实验报告",
        "",
        "## 基本信息",
        "",
        f"- 生成时间：{generated_at.isoformat()}",
        f"- 数据文件：{task.dataset_filename or '未记录'}",
        f"- 运行结论：{_run_conclusion(task)}",
        f"- 任务类型：{task.problem_type or '未解析'}",
        f"- 目标列：{task.label_column or '未解析'}",
        f"- 主指标：{primary_metric}",
        f"- 报告口径：{_report_scope_text(using_artifact_importance)}",
        f"- 成功运行目录：{task.last_run.output_dir if task.last_run else '暂无'}",
        "",
        "---",
        "",
        "## 摘要",
        "",
        *_abstract_lines(task, dataset_profile, agent_loop, feature_importance, candidate_count),
        "",
        "---",
        "",
        "## 1. 任务背景与目标",
        "",
        *_task_background_lines(task, dataset_profile, target_profile, primary_metric),
        "",
        "## 2. 数据整理与质量检查",
        "",
        "### 2.1 数据集概览",
        "",
        *_dataset_overview_lines(dataset_profile, target_profile),
        "",
        "### 2.2 字段与缺失情况",
        "",
        *_field_quality_table_lines(dataset_profile),
        "",
        "### 2.3 数据质量结论",
        "",
        *[f"- {item}" for item in data_quality_notes],
        "",
        "## 3. 自动建模过程与检查清单",
        "",
        "### 3.1 执行流程",
        "",
        *_workflow_report_lines(agent_loop),
        "",
        "### 3.2 检查清单",
        "",
        *_checklist_report_lines(agent_loop),
        "",
        "## 4. 简单对照实验",
        "",
        *_baseline_experiment_lines(agent_loop, task),
        "",
        "## 5. 自动建模实验",
        "",
        "### 5.1 运行结果摘要",
        "",
        *[f"- {item}" for item in result_summary],
        "",
        "### 5.2 候选模型对比",
        "",
        *_model_result_lines(task),
        "",
        "### 5.3 生成文件",
        "",
        *_artifact_report_lines(artifact_index),
    ]
    if agent_loop:
        lines.extend(
            [
                "",
                "## 6. 结果检查与优化过程",
                "",
                "### 6.1 结果检查",
                "",
                *_quality_gate_report_lines(agent_loop),
                "",
                "### 6.2 优化记录",
                "",
                *_tuning_attempt_report_lines(agent_loop),
                "",
                "### 6.3 停止条件",
                "",
                *_stop_condition_report_lines(agent_loop),
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## 6. 结果检查与优化过程",
                "",
                "- 当前任务尚未记录完整检查数据，无法输出简单对照、结果检查和优化复盘。",
            ]
        )
    if feature_importance:
        lines.extend(
            [
                "",
                "## 7. 特征解释与目标关系",
                "",
                "### 7.1 特征重要性/相关性排名",
                "",
                f"- 特征排名来源：{'模型给出的特征重要性' if using_artifact_importance else 'CSV 中特征与目标列的统计关系'}。",
                "",
                *_feature_importance_table_lines(feature_importance),
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## 7. 特征解释与目标关系",
                "",
                "- 当前没有可量化的特征重要性或统计相关性结果。",
            ]
        )
    if relationship_notes:
        lines.extend(
            [
                "",
                "### 7.2 特征与目标关系解读",
                "",
                *[f"- {item}" for item in relationship_notes[:12]],
            ]
        )
    lines.extend(
        [
            "",
            "## 8. 风险和局限",
            "",
            *[f"- {item}" for item in limitation_notes],
            "",
            "## 9. 结论",
            "",
            *_conclusion_lines(task, agent_loop, feature_importance),
            "",
            "## 10. 下一步建议",
            "",
            *_next_step_lines(task, feature_importance),
        ]
    )
    markdown = "\n".join(lines)
    _persist_report_markdown(task, markdown)
    return markdown


def _primary_metric_text(task: TaskRecord) -> str:
    if task.last_run:
        return f"{task.last_run.metric_name} = {_format_metric_value(task.last_run.metric_value)}"
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    metric_name = requirements.get("metric_name")
    return str(metric_name) if metric_name else "未记录"


def _report_scope_text(using_artifact_importance: bool) -> str:
    if using_artifact_importance:
        return "真实结果文件、候选模型对比、模型给出的特征重要性、简单对照与结果检查"
    return "真实结果文件、候选模型对比、简单对照、结果检查，以及 CSV 中特征与目标列的统计关系"


def _abstract_lines(
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
        comparison = _compare_task_to_baseline(task, baseline)
        comparison_text = f"；{_comparison_sentence(comparison)}" if comparison else ""
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


def _artifact_report_lines(artifact_index: Any) -> list[str]:
    rows = [
        ["输出目录", _artifact_status(artifact_index.output_dir), _escape_table_cell(_path_text(artifact_index.output_dir))],
        ["结果摘要", _artifact_status(artifact_index.run_summary_path), _escape_table_cell(_path_text(artifact_index.run_summary_path))],
        ["候选模型对比", _artifact_status(artifact_index.leaderboard_path), _escape_table_cell(_path_text(artifact_index.leaderboard_path))],
        ["AI 使用记录", _artifact_status(artifact_index.token_usage_path), _escape_table_cell(_path_text(artifact_index.token_usage_path))],
        ["生成代码", _artifact_status(artifact_index.generated_code_path), _escape_table_cell(_path_text(artifact_index.generated_code_path))],
    ]
    if artifact_index.feature_importance_paths:
        for index, path in enumerate(artifact_index.feature_importance_paths[:5], start=1):
            rows.append([f"特征重要性 {index}", "已找到", _escape_table_cell(str(path))])
    else:
        rows.append(["特征重要性", "未找到", "未记录"])
    return _markdown_table(["文件", "状态", "路径"], ["---", "---", "---"], rows)


def _feature_importance_table_lines(feature_importance: list[FeatureImportanceEntry]) -> list[str]:
    rows = [
        [str(index), _escape_table_cell(item.feature), _format_metric_value(item.importance), _escape_table_cell(item.source or "unknown")]
        for index, item in enumerate(feature_importance[:15], start=1)
    ]
    return _markdown_table(["排名", "特征", "分数", "来源"], ["---:", "---", "---:", "---"], rows)


def _conclusion_lines(
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
    comparison = _compare_task_to_baseline(task, baseline)
    lines = [
        f"1. 本次自动建模已完成，最佳模型为 {task.last_run.best_model}，{task.last_run.metric_name} = {_format_metric_value(task.last_run.metric_value)}。",
    ]
    if comparison:
        lines.append(f"2. 与简单对照相比，{_comparison_sentence(comparison)}")
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


def format_top_features(feature_importance: list[FeatureImportanceEntry], *, limit: int = 5) -> str:
    return "、".join(f"{item.feature}({item.importance:.3g})" for item in feature_importance[:limit])


def _run_conclusion(task: TaskRecord) -> str:
    if task.last_run:
        return "已完成，可基于本报告做模型验收"
    if task.last_run_attempt and task.last_run_attempt.diagnosis:
        return f"未完成，最后一次运行诊断为：{task.last_run_attempt.diagnosis}"
    if task.status.value == "running":
        return "仍在运行或等待修复，当前报告不是最终成功验收报告"
    return "未完成，尚无成功模型结果"


def _model_result_lines(task: TaskRecord) -> list[str]:
    if not task.last_run:
        attempt = task.last_run_attempt
        lines = ["- 暂无成功模型结果。"]
        if attempt is not None:
            lines.append(f"- 最近运行目录：{attempt.output_dir}。")
            if attempt.diagnosis_detail:
                lines.append(f"- 最近诊断：{attempt.diagnosis_detail}")
        return lines
    lines = [
        f"- 最佳模型：{task.last_run.best_model}",
        f"- 评价指标：{task.last_run.metric_name}",
        f"- 指标数值：{_format_metric_value(task.last_run.metric_value)}",
    ]
    if task.last_run.validation_score is not None:
        lines.append(f"- 候选排序分：{_format_metric_value(task.last_run.validation_score)}")
    if task.last_run.leaderboard:
        rows = []
        for index, row in enumerate(task.last_run.leaderboard[:8], start=1):
            model = row.get("model") or row.get("name") or row.get("model_name") or "unknown"
            score = row.get("validation_score", row.get("score_val"))
            metric_value = row.get("metric_value")
            fit_time = row.get("fit_time")
            pred_time = row.get("pred_time")
            rows.append(
                [
                    str(index),
                    _escape_table_cell(model),
                    _format_metric_value(score),
                    _format_metric_value(metric_value),
                    _format_metric_value(fit_time),
                    _format_metric_value(pred_time),
                ]
            )
        lines.extend(["", *_markdown_table(["排名", "模型", "validation_score", "metric_value", "fit_time", "pred_time"], ["---:", "---", "---:", "---:", "---:", "---:"], rows)])
    else:
        lines.append("- 当前没有解析到候选模型对比结果。")
    return lines


def _next_step_lines(task: TaskRecord, feature_importance: list[FeatureImportanceEntry]) -> list[str]:
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


def _persist_report_markdown(task: TaskRecord, markdown: str) -> None:
    output_dir = None
    if task.last_run and task.last_run.output_dir:
        output_dir = Path(task.last_run.output_dir)
    elif task.last_run_attempt and task.last_run_attempt.output_dir:
        output_dir = Path(task.last_run_attempt.output_dir)
    if output_dir is None or not output_dir.exists():
        return
    try:
        (output_dir / "final_report.md").write_text(markdown, encoding="utf-8")
    except OSError:
        return
