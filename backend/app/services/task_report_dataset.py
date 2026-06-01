from __future__ import annotations

from typing import Any

from backend.app.models.task import DatasetProfile, TaskRecord
from backend.app.services.task_report_formatting import (
    escape_table_cell as _escape_table_cell,
    format_integer as _format_integer,
    format_metric_value as _format_metric_value,
    format_percent as _format_percent,
    markdown_table as _markdown_table,
)


def task_background_lines(
    task: TaskRecord,
    profile: DatasetProfile | None,
    target_profile: dict[str, Any],
    primary_metric_text: str,
) -> list[str]:
    rows = [
        f"- 业务描述：{task.description or '未填写'}",
        f"- 建模目标：使用 CSV 中的特征字段预测 `{task.label_column or '未确认目标列'}`。",
        f"- 问题类型：{task.problem_type or '未解析'}。",
        f"- 评价指标：{primary_metric_text}。",
        "- 交付内容：数据质量检查、简单对照、自动建模结果、候选模型比较、结果检查、优化复盘和下一步建议。",
    ]
    if profile is not None:
        rows.append(f"- 数据规模：{_format_integer(profile.row_count)} 行、{_format_integer(profile.column_count)} 列。")
    if target_profile.get("status") == "available":
        rows.append(
            f"- 目标列画像：非空样本 {_format_integer(target_profile.get('count'))}，"
            f"不同取值 {_format_integer(target_profile.get('distinct_count'))}。"
        )
    return rows


def dataset_overview_lines(profile: DatasetProfile | None, target_profile: dict[str, Any]) -> list[str]:
    if profile is None:
        return ["- 当前没有可读取的数据集画像。"]
    lines = [
        "| 项目 | 数值 |",
        "| --- | --- |",
        f"| 文件名 | {_escape_table_cell(profile.filename or '未记录')} |",
        f"| 样本行数 | {_format_integer(profile.row_count)} |",
        f"| 字段数 | {_format_integer(profile.column_count)} |",
        f"| 目标列 | {_escape_table_cell(profile.target_column or '未记录')} |",
        f"| 画像生成时间 | {_escape_table_cell(profile.generated_at.isoformat())} |",
        "",
        "目标列统计如下。",
        "",
    ]
    if target_profile.get("status") != "available":
        lines.append(f"- {target_profile.get('detail') or '目标列统计不可用。'}")
        return lines
    if target_profile.get("kind") == "numeric":
        lines.extend(
            [
                "| 统计量 | 数值 |",
                "| --- | ---: |",
                f"| 非空样本数 | {_format_integer(target_profile.get('count'))} |",
                f"| 均值 | {_format_metric_value(target_profile.get('mean'))} |",
                f"| 标准差 | {_format_metric_value(target_profile.get('std'))} |",
                f"| 最小值 | {_format_metric_value(target_profile.get('min'))} |",
                f"| 25% 分位数 | {_format_metric_value(target_profile.get('q1'))} |",
                f"| 中位数 | {_format_metric_value(target_profile.get('median'))} |",
                f"| 75% 分位数 | {_format_metric_value(target_profile.get('q3'))} |",
                f"| 最大值 | {_format_metric_value(target_profile.get('max'))} |",
            ]
        )
        return lines
    lines.extend(
        [
            f"- 目标列共有 {_format_integer(target_profile.get('class_count'))} 个不同取值；下表展示出现次数最多的类别。",
            "",
            "| 类别 | 数量 | 占比 |",
            "| --- | ---: | ---: |",
        ]
    )
    for item in target_profile.get("top_values") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {_escape_table_cell(item.get('value'))} | {_format_integer(item.get('count'))} | {_format_percent(item.get('ratio'))} |"
        )
    return lines


def field_quality_table_lines(profile: DatasetProfile | None) -> list[str]:
    if profile is None:
        return ["- 当前没有字段画像，无法输出字段级质量表。"]
    rows = []
    for column in profile.columns[:30]:
        sample_values = "、".join(column.sample_values[:3]) if column.sample_values else ""
        rows.append(
            [
                _escape_table_cell(column.name),
                _escape_table_cell(column.inferred_type),
                _format_integer(column.non_empty_count),
                _format_integer(column.missing_count),
                _format_percent(column.missing_ratio),
                _escape_table_cell(sample_values or "无"),
            ]
        )
    lines = _markdown_table(["字段", "推断类型", "非空数", "缺失数", "缺失率", "示例值"], ["---", "---", "---:", "---:", "---:", "---"], rows)
    if len(profile.columns) > 30:
        lines.append(f"- 字段数量较多，表格仅展示前 30 个字段；完整字段数为 {_format_integer(len(profile.columns))}。")
    return lines
