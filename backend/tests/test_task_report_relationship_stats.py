from __future__ import annotations

from backend.app.services.task_report_relationship_stats import (
    absolute_pearson,
    cramers_v,
    relationship_strength,
    score_feature_relationship,
    to_float,
)


def test_score_feature_relationship_uses_pearson_for_numeric_target_and_feature() -> None:
    score, method, source = score_feature_relationship(
        ["1", "2", "3"],
        [1.0, 2.0, 3.0],
        ["2", "4", "6"],
        [2.0, 4.0, 6.0],
        target_is_numeric=True,
    )

    assert score == 1.0
    assert method == "Pearson 线性相关"
    assert source == "dataset_correlation"


def test_score_feature_relationship_uses_categorical_association_for_categorical_pairs() -> None:
    score, method, source = score_feature_relationship(
        ["A", "A", "B", "B"],
        [None, None, None, None],
        ["yes", "yes", "no", "no"],
        [None, None, None, None],
        target_is_numeric=False,
    )

    assert score == 1.0
    assert method == "Cramer's V 类别关联"
    assert source == "dataset_categorical_association"


def test_relationship_strength_and_numeric_parsing_boundaries() -> None:
    assert relationship_strength(0.8) == "强"
    assert relationship_strength(0.5) == "中等"
    assert relationship_strength(0.25) == "较弱"
    assert relationship_strength(0.1) == "很弱"
    assert to_float("") is None
    assert to_float("not-a-number") is None
    assert to_float("inf") is None
    assert to_float("2.5") == 2.5


def test_low_information_relationships_return_none() -> None:
    assert absolute_pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert cramers_v(["A", "A"], ["yes", "no"]) is None
