from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetProfile, FeatureImportanceEntry, TaskRecord
from backend.app.services.dataset_profile import read_dataset_rows
from backend.app.services.task_report_relationship_stats import (
    MIN_RELATIONSHIP_PAIRS,
    relationship_strength,
    score_feature_relationship,
    to_float,
    usable_numeric_count,
)
from backend.app.services.task_targets import target_columns_display, target_columns_from_task


MAX_RELATIONSHIP_ROWS = 20_000


@dataclass(frozen=True)
class _TargetRelationship:
    column: str
    values: list[str]
    numeric_values: list[float | None]
    is_numeric: bool


def collect_feature_relationships(
    task: TaskRecord,
    profile: DatasetProfile | None,
) -> tuple[list[FeatureImportanceEntry], list[str]]:
    target_column = _target_column(task, profile)
    if not target_column or not task.dataset_path:
        return [], ["缺少目标列或数据集路径，无法计算特征与目标列的关系。"]
    target_columns = target_columns_from_task(task)
    if len(target_columns) > 1:
        targets = target_columns_display(target_columns)
        return [], [f"当前是多目标任务（{targets}），特征关系分析由 Codex 产物呈现。"]

    fieldnames, rows, load_error = _load_relationship_rows(Path(task.dataset_path), target_column)
    if load_error:
        return [], [load_error]
    if not rows:
        return [], ["数据集没有可分析的数据行，无法计算特征与目标列的关系。"]

    target = _target_relationship(target_column, rows)
    entries, notes = _feature_relationships(fieldnames, rows, target)
    return _relationship_result(target_column, entries, notes)


def _target_column(task: TaskRecord, profile: DatasetProfile | None) -> str | None:
    targets = target_columns_from_task(task)
    if len(targets) == 1:
        return targets[0]
    return task.label_column or (profile.target_column if profile else None)


def _target_relationship(target_column: str, rows: list[dict[str, str]]) -> _TargetRelationship:
    target_values = [_clean_cell(row.get(target_column)) for row in rows]
    target_numeric = [to_float(value) for value in target_values]
    return _TargetRelationship(
        column=target_column,
        values=target_values,
        numeric_values=target_numeric,
        is_numeric=usable_numeric_count(target_numeric) >= MIN_RELATIONSHIP_PAIRS,
    )


def _feature_relationships(
    fieldnames: list[str],
    rows: list[dict[str, str]],
    target: _TargetRelationship,
) -> tuple[list[FeatureImportanceEntry], list[str]]:
    entries: list[FeatureImportanceEntry] = []
    notes: list[str] = []

    for feature in fieldnames:
        if feature == target.column:
            continue
        relationship = _feature_relationship(feature, rows, target)
        if relationship is None:
            continue
        entry, note = relationship
        entries.append(entry)
        notes.append(note)
    return entries, notes


def _feature_relationship(
    feature: str,
    rows: list[dict[str, str]],
    target: _TargetRelationship,
) -> tuple[FeatureImportanceEntry, str] | None:
    values = [_clean_cell(row.get(feature)) for row in rows]
    numeric_values = [to_float(value) for value in values]
    score, method, source = score_feature_relationship(
        values,
        numeric_values,
        target.values,
        target.numeric_values,
        target_is_numeric=target.is_numeric,
    )
    if score is None or not math.isfinite(score):
        return None
    return (
        FeatureImportanceEntry(feature=feature, importance=score, source=source),
        f"{feature} 与目标列 {target.column} 的{method}为 {score:.3f}，属于{relationship_strength(score)}关系。",
    )


def _relationship_result(
    target_column: str,
    entries: list[FeatureImportanceEntry],
    notes: list[str],
) -> tuple[list[FeatureImportanceEntry], list[str]]:
    entries = sorted(entries, key=lambda item: abs(item.importance), reverse=True)[:20]
    if not entries:
        return [], ["未找到足够的数值或可分组字段来计算稳定的特征关系。"]
    top_names = "、".join(item.feature for item in entries[:5])
    return entries, [f"按与目标列 {target_column} 的关系强度排序，当前最相关的特征是：{top_names}。", *notes[:10]]


def _load_relationship_rows(dataset_path: Path, target_column: str) -> tuple[list[str], list[dict[str, str]], str]:
    if not dataset_path.exists():
        return [], [], "数据集文件不存在，无法计算特征与目标列的关系。"

    rows: list[dict[str, str]] = []
    try:
        fieldnames, rows = read_dataset_rows(dataset_path, max_rows=MAX_RELATIONSHIP_ROWS)
        if not fieldnames or target_column not in fieldnames:
            return [], [], f"数据集中没有找到目标列 {target_column}，无法计算特征与目标列的关系。"
    except OSError as exc:
        return [], [], f"读取数据集失败，无法计算特征与目标列的关系：{exc}"
    return fieldnames, rows, ""


def _clean_cell(value: Any) -> str:
    return "" if value is None else str(value).strip()
