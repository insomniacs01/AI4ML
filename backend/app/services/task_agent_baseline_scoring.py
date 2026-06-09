from __future__ import annotations

import math
from collections import Counter
from typing import Any

from backend.app.services.tabular_numeric import parse_tabular_float


MAX_PREVIEW_DISTINCT_VALUES = 200


def finite_numeric_values(raw_values: list[str]) -> list[float]:
    numeric_values: list[float] = []
    for value in raw_values:
        numeric = parse_tabular_float(value)
        if numeric is not None:
            numeric_values.append(numeric)
    return numeric_values


def regression_scores(validation: list[float], prediction: float) -> dict[str, float]:
    errors = [value - prediction for value in validation]
    squared_errors = [error * error for error in errors]
    mean_validation = sum(validation) / len(validation)
    total_ss = sum((value - mean_validation) ** 2 for value in validation)
    residual_ss = sum(squared_errors)
    return {
        "rmse": math.sqrt(residual_ss / len(errors)),
        "mae": sum(abs(error) for error in errors) / len(errors),
        "mse": residual_ss / len(errors),
        "r2": 1 - residual_ss / total_ss if total_ss > 0 else 0.0,
    }


def classification_scores(train: list[str], validation: list[str], majority_label: str) -> dict[str, float]:
    predictions = [majority_label for _value in validation]
    accuracy = classification_accuracy(predictions, validation)
    scores = {
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy(predictions, validation, accuracy),
    }
    if len(set(train)) == 2:
        scores["f1"] = binary_f1(predictions, validation, majority_label)
    return scores


def classification_accuracy(predictions: list[str], validation: list[str]) -> float:
    return sum(1 for prediction, actual in zip(predictions, validation) if prediction == actual) / len(validation)


def balanced_accuracy(predictions: list[str], validation: list[str], fallback: float) -> float:
    recalls = []
    for label in sorted(set(validation)):
        total = sum(1 for value in validation if value == label)
        correct = sum(1 for prediction, actual in zip(predictions, validation) if actual == label and prediction == actual)
        recalls.append(correct / total if total else 0.0)
    return sum(recalls) / len(recalls) if recalls else fallback


def binary_f1(predictions: list[str], validation: list[str], positive: str) -> float:
    tp = sum(1 for prediction, actual in zip(predictions, validation) if prediction == positive and actual == positive)
    fp = sum(1 for prediction, actual in zip(predictions, validation) if prediction == positive and actual != positive)
    fn = sum(1 for prediction, actual in zip(predictions, validation) if prediction != positive and actual == positive)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def class_distribution(counts: Counter[str]) -> dict[str, int]:
    return {str(label): count for label, count in counts.most_common(MAX_PREVIEW_DISTINCT_VALUES)}


def deterministic_split(values: list[Any]) -> tuple[list[Any], list[Any]]:
    validation = [value for index, value in enumerate(values) if index % 5 == 0]
    train = [value for index, value in enumerate(values) if index % 5 != 0]
    if not validation and values:
        validation = values[-1:]
        train = values[:-1]
    return train, validation
