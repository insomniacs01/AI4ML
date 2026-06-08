from __future__ import annotations

from backend.app.models.task import DatasetProfile, FeatureImportanceEntry, TaskRecord
from backend.app.services.task_report_narrative import format_top_features


def build_result_summary(
    task: TaskRecord,
    *,
    feature_importance: list[FeatureImportanceEntry],
    relationship_notes: list[str],
    using_artifact_importance: bool,
) -> list[str]:
    if not task.last_run:
        return [
            "当前任务还没有成功的自动建模结果；本报告只能给出数据与特征关系诊断，不能作为最终模型验收报告。",
            *relationship_notes[:3],
        ]
    leaderboard_count = len(task.last_run.leaderboard or [])
    summary = [
        f"最佳模型为 {task.last_run.best_model}。",
        f"主要指标 {task.last_run.metric_name} = {task.last_run.metric_value:.6g}。",
        f"本次成功解析到 {leaderboard_count} 个候选模型结果。",
        f"结果文件目录：{task.last_run.output_dir}。",
    ]
    if feature_importance:
        source_label = "模型给出的特征重要性" if using_artifact_importance else "数据集与目标列相关性分析"
        summary.append(f"按{source_label}看，最重要/最相关的特征包括：{format_top_features(feature_importance)}。")
    else:
        summary.append("当前没有可量化的特征重要性或相关性结果，模型解释性不足。")
    return summary


def build_data_quality_notes(profile: DatasetProfile | None) -> list[str]:
    if profile is None:
        return ["当前没有可读取的数据集画像。"]
    notes = [
        f"数据集包含 {profile.row_count} 行、{profile.column_count} 列。",
    ]
    columns_with_missing = [column for column in profile.columns if column.missing_count > 0]
    if columns_with_missing:
        worst = sorted(columns_with_missing, key=lambda item: item.missing_ratio, reverse=True)[:5]
        notes.append(
            "存在缺失值的字段包括："
            + "、".join(f"{item.name}({item.missing_ratio:.1%})" for item in worst)
            + "。"
        )
    else:
        notes.append("预览范围内未发现缺失值。")
    if profile.target_column:
        notes.append(f"当前目标列为 {profile.target_column}。")
    return notes


def build_limitation_notes(
    task: TaskRecord,
    profile: DatasetProfile | None,
    feature_importance: list[FeatureImportanceEntry],
    *,
    relationship_notes: list[str],
    using_artifact_importance: bool,
) -> list[str]:
    notes: list[str] = []
    if profile is not None and profile.row_count < 100:
        notes.append("数据行数较少，验证指标可能对划分方式敏感。")
    if not feature_importance:
        notes.append("当前没有可解析的特征重要性文件，也无法从数据集中计算稳定的特征关系，因此模型解释性不足。")
    elif not using_artifact_importance:
        notes.append("当前报告没有拿到模型给出的特征重要性；特征排名来自数据集和目标列的统计关系，只说明相关性，不等价于因果关系。")
    if relationship_notes and relationship_notes[0].startswith("未找到"):
        notes.append(relationship_notes[0])
    if task.last_run and len(task.last_run.leaderboard or []) <= 1:
        notes.append("候选模型数量较少，模型选择结论的稳定性有限。")
    if not notes:
        notes.append("当前报告仅基于最近一次成功结果，不代表生产环境长期表现。")
    return notes
