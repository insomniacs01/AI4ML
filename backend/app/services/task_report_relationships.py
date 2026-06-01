from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetProfile, FeatureImportanceEntry, TaskRecord


MAX_RELATIONSHIP_ROWS = 20_000
MAX_CATEGORICAL_VALUES = 80
MIN_RELATIONSHIP_PAIRS = 3


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

    fieldnames, rows, load_error = _load_relationship_rows(Path(task.dataset_path), target_column)
    if load_error:
        return [], [load_error]
    if not rows:
        return [], ["数据集没有可分析的数据行，无法计算特征与目标列的关系。"]

    target = _target_relationship(target_column, rows)
    entries, notes = _feature_relationships(fieldnames, rows, target)
    return _relationship_result(target_column, entries, notes)


def _target_column(task: TaskRecord, profile: DatasetProfile | None) -> str | None:
    return task.label_column or (profile.target_column if profile else None)


def _target_relationship(target_column: str, rows: list[dict[str, str]]) -> _TargetRelationship:
    target_values = [_clean_cell(row.get(target_column)) for row in rows]
    target_numeric = [_to_float(value) for value in target_values]
    return _TargetRelationship(
        column=target_column,
        values=target_values,
        numeric_values=target_numeric,
        is_numeric=_usable_numeric_count(target_numeric) >= MIN_RELATIONSHIP_PAIRS,
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
    numeric_values = [_to_float(value) for value in values]
    score, method, source = _score_feature_relationship(
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
        f"{feature} 与目标列 {target.column} 的{method}为 {score:.3f}，属于{_relationship_strength(score)}关系。",
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
        with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or target_column not in reader.fieldnames:
                return [], [], f"数据集中没有找到目标列 {target_column}，无法计算特征与目标列的关系。"
            fieldnames = list(reader.fieldnames)
            for index, row in enumerate(reader):
                if index >= MAX_RELATIONSHIP_ROWS:
                    break
                rows.append(row)
    except OSError as exc:
        return [], [], f"读取数据集失败，无法计算特征与目标列的关系：{exc}"
    return fieldnames, rows, ""


def _score_feature_relationship(
    values: list[str],
    numeric_values: list[float | None],
    target_values: list[str],
    target_numeric: list[float | None],
    *,
    target_is_numeric: bool,
) -> tuple[float | None, str, str]:
    if target_is_numeric and _usable_numeric_count(numeric_values) >= MIN_RELATIONSHIP_PAIRS:
        return _absolute_pearson(numeric_values, target_numeric), "Pearson 线性相关", "dataset_correlation"
    if target_is_numeric:
        return _categorical_target_eta(values, target_numeric), "类别分组解释度", "dataset_group_effect"
    if _usable_numeric_count(numeric_values) >= MIN_RELATIONSHIP_PAIRS:
        return (
            _numeric_feature_categorical_target_eta(numeric_values, target_values),
            "按目标类别的数值分组差异",
            "dataset_group_effect",
        )
    return _cramers_v(values, target_values), "Cramer's V 类别关联", "dataset_categorical_association"


def _relationship_strength(score: float) -> str:
    if score >= 0.75:
        return "强"
    if score >= 0.45:
        return "中等"
    if score >= 0.2:
        return "较弱"
    return "很弱"


def _clean_cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _to_float(value: str) -> float | None:
    if value == "":
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def _usable_numeric_count(values: list[float | None]) -> int:
    return sum(1 for value in values if value is not None)


def _absolute_pearson(feature_values: list[float | None], target_values: list[float | None]) -> float | None:
    pairs = [
        (feature, target)
        for feature, target in zip(feature_values, target_values)
        if feature is not None and target is not None
    ]
    if len(pairs) < MIN_RELATIONSHIP_PAIRS:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return abs(covariance / math.sqrt(var_x * var_y))


def _categorical_target_eta(feature_values: list[str], target_values: list[float | None]) -> float | None:
    groups: dict[str, list[float]] = {}
    for feature, target in zip(feature_values, target_values):
        if target is None or feature == "":
            continue
        groups.setdefault(feature, []).append(target)
        if len(groups) > MAX_CATEGORICAL_VALUES:
            return None
    groups = {key: values for key, values in groups.items() if values}
    if len(groups) < 2:
        return None
    all_values = [value for values in groups.values() for value in values]
    if len(all_values) < MIN_RELATIONSHIP_PAIRS:
        return None
    grand_mean = sum(all_values) / len(all_values)
    total_ss = sum((value - grand_mean) ** 2 for value in all_values)
    if total_ss <= 0:
        return None
    between_ss = sum(len(values) * ((sum(values) / len(values)) - grand_mean) ** 2 for values in groups.values())
    return math.sqrt(max(0.0, min(1.0, between_ss / total_ss)))


def _numeric_feature_categorical_target_eta(feature_values: list[float | None], target_values: list[str]) -> float | None:
    groups: dict[str, list[float]] = {}
    for feature, target in zip(feature_values, target_values):
        if feature is None or target == "":
            continue
        groups.setdefault(target, []).append(feature)
        if len(groups) > MAX_CATEGORICAL_VALUES:
            return None
    groups = {key: values for key, values in groups.items() if values}
    if len(groups) < 2:
        return None
    all_values = [value for values in groups.values() for value in values]
    if len(all_values) < MIN_RELATIONSHIP_PAIRS:
        return None
    grand_mean = sum(all_values) / len(all_values)
    total_ss = sum((value - grand_mean) ** 2 for value in all_values)
    if total_ss <= 0:
        return None
    between_ss = sum(len(values) * ((sum(values) / len(values)) - grand_mean) ** 2 for values in groups.values())
    return math.sqrt(max(0.0, min(1.0, between_ss / total_ss)))


def _cramers_v(feature_values: list[str], target_values: list[str]) -> float | None:
    table: dict[str, dict[str, int]] = {}
    row_totals: dict[str, int] = {}
    column_totals: dict[str, int] = {}
    total = 0
    for feature, target in zip(feature_values, target_values):
        if feature == "" or target == "":
            continue
        table.setdefault(feature, {})
        table[feature][target] = table[feature].get(target, 0) + 1
        row_totals[feature] = row_totals.get(feature, 0) + 1
        column_totals[target] = column_totals.get(target, 0) + 1
        total += 1
        if len(row_totals) > MAX_CATEGORICAL_VALUES or len(column_totals) > MAX_CATEGORICAL_VALUES:
            return None
    if total < MIN_RELATIONSHIP_PAIRS or len(row_totals) < 2 or len(column_totals) < 2:
        return None
    chi_square = 0.0
    for feature, row_total in row_totals.items():
        for target, column_total in column_totals.items():
            expected = row_total * column_total / total
            if expected <= 0:
                continue
            observed = table.get(feature, {}).get(target, 0)
            chi_square += (observed - expected) ** 2 / expected
    denominator = total * min(len(row_totals) - 1, len(column_totals) - 1)
    if denominator <= 0:
        return None
    return math.sqrt(max(0.0, min(1.0, chi_square / denominator)))
