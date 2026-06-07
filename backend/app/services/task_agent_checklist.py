from __future__ import annotations

from typing import Any

from backend.app.models.task import DatasetProfile, TaskRecord
from backend.app.services.task_agent_baseline_metrics import resolve_metric_name
from backend.app.services.task_targets import target_columns_display, target_columns_from_task


def build_checklist(task: TaskRecord) -> list[dict[str, Any]]:
    profile = task.dataset_profile
    metric_name = resolve_metric_name(task)
    items = _base_checklist_items(task, profile, metric_name)
    target_check = _target_column_check(task, profile)
    if target_check:
        items.append(target_check)
    items.extend(_profile_risk_checks(profile))
    return items


def _base_checklist_items(
    task: TaskRecord,
    profile: DatasetProfile | None,
    metric_name: str,
) -> list[dict[str, Any]]:
    target_columns = target_columns_from_task(task)
    return [
        _check_item(
            "dataset_uploaded",
            "数据已上传",
            "passed" if task.dataset_path else "blocked",
            f"数据文件：{task.dataset_filename or '未上传'}",
            task.dataset_path,
        ),
        _check_item(
            "dataset_profile",
            "数据画像已生成",
            "passed" if profile and profile.column_count > 0 else "blocked",
            profile_summary(profile),
            "dataset_profile",
        ),
        _check_item(
            "target_column",
            "预测目标已确认",
            "passed" if target_columns else "pending",
            f"目标列：{target_columns_display(target_columns) or '等待 AI 或人工确认'}",
            target_columns or task.label_column,
        ),
        _check_item(
            "problem_type",
            "问题类型已确认",
            "passed" if task.problem_type in {"classification", "regression"} else "pending",
            f"问题类型：{task.problem_type or '等待确认'}",
            task.problem_type,
        ),
        _check_item(
            "metric_name",
            "评价指标已确认",
            "passed" if metric_name else "pending",
            f"指标：{metric_name or '等待确认'}",
            metric_name,
        ),
    ]


def _target_column_check(task: TaskRecord, profile: DatasetProfile | None) -> dict[str, Any] | None:
    target_columns = target_columns_from_task(task)
    if not target_columns:
        return None
    target_text = target_columns_display(target_columns)
    if profile and profile.columns:
        missing = [column for column in target_columns if column not in _profile_column_names(profile)]
        if missing:
            return _check_item(
                "target_in_columns",
                "目标列存在于数据表头",
                "blocked",
                f"目标列 {target_columns_display(missing)} 不在当前数据表头中。",
                target_columns if len(target_columns) > 1 else target_columns[0],
            )
    if len(target_columns) > 1:
        return _check_item(
            "target_in_columns",
            "多目标列已记录",
            "passed",
            f"已记录多目标列：{target_text}。",
            target_columns,
        )
    return _check_item(
        "target_in_columns",
        "目标列存在于数据表头",
        "passed",
        f"已记录目标列 {target_text}。",
        target_columns[0],
    )


def _profile_column_names(profile: DatasetProfile) -> set[str]:
    return {column.name for column in profile.columns}


def _profile_risk_checks(profile: DatasetProfile | None) -> list[dict[str, Any]]:
    if not profile:
        return []
    return [_missing_values_check(profile), _sample_size_check(profile)]


def _missing_values_check(profile: DatasetProfile) -> dict[str, Any]:
    missing_warnings = [column for column in profile.columns if column.missing_ratio >= 0.3]
    return _check_item(
        "missing_values",
        "缺失值风险检查",
        "warning" if missing_warnings else "passed",
        _missing_values_detail(missing_warnings),
        "dataset_profile.columns",
    )


def _missing_values_detail(missing_warnings: list[Any]) -> str:
    if not missing_warnings:
        return "未发现缺失比例超过 30% 的字段。"
    return "高缺失字段：" + "、".join(
        f"{item.name}({item.missing_ratio:.0%})" for item in missing_warnings[:5]
    )


def _sample_size_check(profile: DatasetProfile) -> dict[str, Any]:
    if profile.row_count < 30:
        return _check_item(
            "sample_size",
            "样本量检查",
            "warning",
            "样本量较少，模型验证结果可能不稳定。",
            profile.row_count,
        )
    return _check_item("sample_size", "样本量检查", "passed", "样本量达到轻量验证的最低要求。", profile.row_count)


def profile_summary(profile: DatasetProfile | None) -> str:
    if profile is None:
        return "尚未生成数据画像。"
    return f"{profile.row_count} 行，{profile.column_count} 列。"


def _check_item(item_id: str, title: str, status: str, detail: str, evidence: Any = None) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "status": status,
        "detail": detail,
        "evidence": evidence,
    }
