from __future__ import annotations

import math
from collections import Counter

from backend.app.services.task_agent_baseline_scoring import (
    balanced_accuracy,
    binary_f1,
    class_distribution,
    classification_accuracy,
    classification_scores,
    deterministic_split,
    finite_numeric_values,
    regression_scores,
)


def test_deterministic_split_uses_every_fifth_row_for_validation() -> None:
    train, validation = deterministic_split(list(range(10)))

    assert train == [1, 2, 3, 4, 6, 7, 8, 9]
    assert validation == [0, 5]


def test_finite_numeric_values_filters_invalid_and_non_finite_values() -> None:
    assert finite_numeric_values(["1", "not-number", "nan", "inf", "-2.5"]) == [1.0, -2.5]


def test_regression_scores_include_rmse_mae_mse_and_r2() -> None:
    scores = regression_scores([1.0, 5.0], prediction=3.0)

    assert scores["rmse"] == 2.0
    assert scores["mae"] == 2.0
    assert scores["mse"] == 4.0
    assert scores["r2"] == 0.0


def test_classification_scores_include_binary_f1_for_two_training_classes() -> None:
    scores = classification_scores(["yes", "yes", "no"], ["yes", "no", "yes"], "yes")

    assert math.isclose(scores["accuracy"], 2 / 3)
    assert math.isclose(scores["balanced_accuracy"], 0.5)
    assert math.isclose(scores["f1"], 0.8)
    assert classification_accuracy(["a", "b"], ["a", "a"]) == 0.5
    assert balanced_accuracy(["a", "a"], ["a", "b"], fallback=0.5) == 0.5
    assert binary_f1(["a", "b"], ["b", "a"], "a") == 0.0


def test_class_distribution_keeps_most_common_order() -> None:
    assert class_distribution(Counter({"yes": 3, "no": 1})) == {"yes": 3, "no": 1}
