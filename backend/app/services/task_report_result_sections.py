from __future__ import annotations

from typing import Any

from backend.app.models.task import FeatureImportanceEntry, TaskRecord
from backend.app.services.task_report_formatting import (
    artifact_status,
    escape_table_cell,
    format_metric_value,
    markdown_table,
    path_text,
)


def artifact_report_lines(artifact_index: Any) -> list[str]:
    rows = [
        ["输出目录", artifact_status(artifact_index.output_dir), escape_table_cell(path_text(artifact_index.output_dir))],
        ["结果摘要", artifact_status(artifact_index.run_summary_path), escape_table_cell(path_text(artifact_index.run_summary_path))],
        ["候选模型对比", artifact_status(artifact_index.leaderboard_path), escape_table_cell(path_text(artifact_index.leaderboard_path))],
        ["AI 使用记录", artifact_status(artifact_index.token_usage_path), escape_table_cell(path_text(artifact_index.token_usage_path))],
        ["生成代码", artifact_status(artifact_index.generated_code_path), escape_table_cell(path_text(artifact_index.generated_code_path))],
    ]
    if artifact_index.feature_importance_paths:
        for index, path in enumerate(artifact_index.feature_importance_paths[:5], start=1):
            rows.append([f"特征重要性 {index}", "已找到", escape_table_cell(str(path))])
    else:
        rows.append(["特征重要性", "未找到", "未记录"])
    return markdown_table(["文件", "状态", "路径"], ["---", "---", "---"], rows)


def feature_importance_table_lines(feature_importance: list[FeatureImportanceEntry]) -> list[str]:
    rows = [
        [str(index), escape_table_cell(item.feature), format_metric_value(item.importance), escape_table_cell(item.source or "unknown")]
        for index, item in enumerate(feature_importance[:15], start=1)
    ]
    return markdown_table(["排名", "特征", "分数", "来源"], ["---:", "---", "---:", "---"], rows)


def model_result_lines(task: TaskRecord) -> list[str]:
    if not task.last_run:
        return _missing_model_result_lines(task)
    lines = [
        f"- 最佳模型：{task.last_run.best_model}",
        f"- 评价指标：{task.last_run.metric_name}",
        f"- 指标数值：{format_metric_value(task.last_run.metric_value)}",
    ]
    if task.last_run.validation_score is not None:
        lines.append(f"- 候选排序分：{format_metric_value(task.last_run.validation_score)}")
    if task.last_run.leaderboard:
        lines.extend(["", *_leaderboard_table_lines(task.last_run.leaderboard)])
    else:
        lines.append("- 当前没有解析到候选模型对比结果。")
    return lines


def _missing_model_result_lines(task: TaskRecord) -> list[str]:
    attempt = task.last_run_attempt
    lines = ["- 暂无成功模型结果。"]
    if attempt is not None:
        lines.append(f"- 最近运行目录：{attempt.output_dir}。")
        if attempt.diagnosis_detail:
            lines.append(f"- 最近诊断：{attempt.diagnosis_detail}")
    return lines


def _leaderboard_table_lines(leaderboard: list[dict[str, Any]]) -> list[str]:
    rows = []
    for index, row in enumerate(leaderboard[:8], start=1):
        model = row.get("model") or row.get("name") or row.get("model_name") or "unknown"
        score = row.get("validation_score", row.get("score_val"))
        metric_value = row.get("metric_value")
        fit_time = row.get("fit_time")
        pred_time = row.get("pred_time")
        rows.append(
            [
                str(index),
                escape_table_cell(model),
                format_metric_value(score),
                format_metric_value(metric_value),
                format_metric_value(fit_time),
                format_metric_value(pred_time),
            ]
        )
    return markdown_table(
        ["排名", "模型", "validation_score", "metric_value", "fit_time", "pred_time"],
        ["---:", "---", "---:", "---:", "---:", "---:"],
        rows,
    )
