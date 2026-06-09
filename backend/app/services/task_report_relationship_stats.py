from __future__ import annotations

import math

from backend.app.services.tabular_numeric import parse_tabular_float


MAX_CATEGORICAL_VALUES = 80
MIN_RELATIONSHIP_PAIRS = 3


def score_feature_relationship(
    values: list[str],
    numeric_values: list[float | None],
    target_values: list[str],
    target_numeric: list[float | None],
    *,
    target_is_numeric: bool,
) -> tuple[float | None, str, str]:
    if target_is_numeric and usable_numeric_count(numeric_values) >= MIN_RELATIONSHIP_PAIRS:
        return absolute_pearson(numeric_values, target_numeric), "Pearson 线性相关", "dataset_correlation"
    if target_is_numeric:
        return categorical_target_eta(values, target_numeric), "类别分组解释度", "dataset_group_effect"
    if usable_numeric_count(numeric_values) >= MIN_RELATIONSHIP_PAIRS:
        return (
            numeric_feature_categorical_target_eta(numeric_values, target_values),
            "按目标类别的数值分组差异",
            "dataset_group_effect",
        )
    return cramers_v(values, target_values), "Cramer's V 类别关联", "dataset_categorical_association"


def relationship_strength(score: float) -> str:
    if score >= 0.75:
        return "强"
    if score >= 0.45:
        return "中等"
    if score >= 0.2:
        return "较弱"
    return "很弱"


def to_float(value: str) -> float | None:
    return parse_tabular_float(value)


def usable_numeric_count(values: list[float | None]) -> int:
    return sum(1 for value in values if value is not None)


def absolute_pearson(feature_values: list[float | None], target_values: list[float | None]) -> float | None:
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


def categorical_target_eta(feature_values: list[str], target_values: list[float | None]) -> float | None:
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


def numeric_feature_categorical_target_eta(feature_values: list[float | None], target_values: list[str]) -> float | None:
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


def cramers_v(feature_values: list[str], target_values: list[str]) -> float | None:
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
