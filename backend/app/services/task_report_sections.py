from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backend.app.models.task import DatasetProfile, FeatureImportanceEntry, TaskRecord
from backend.app.services.task_artifacts import build_run_artifact_index
from backend.app.services.task_report_formatting import format_metric_value as _format_metric_value
from backend.app.services.task_report_narrative import (
    abstract_lines as _abstract_lines,
    conclusion_lines as _conclusion_lines,
    next_step_lines as _next_step_lines,
    run_conclusion as _run_conclusion,
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
    quality_gate_report_lines as _quality_gate_report_lines,
    stop_condition_report_lines as _stop_condition_report_lines,
    tuning_attempt_report_lines as _tuning_attempt_report_lines,
    workflow_report_lines as _workflow_report_lines,
)
from backend.app.services.task_report_result_sections import (
    artifact_report_lines as _artifact_report_lines,
    feature_importance_table_lines as _feature_importance_table_lines,
    model_result_lines as _model_result_lines,
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
