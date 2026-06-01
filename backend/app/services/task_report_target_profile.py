from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetProfile, TaskRecord
from backend.app.services.task_targets import target_columns_display, target_columns_from_task


MAX_TARGET_PROFILE_ROWS = 50_000


@dataclass(frozen=True)
class _TargetValueSample:
    values: list[str]
    scanned_rows: int
    source: str
    detail: str = ""


def build_target_profile(task: TaskRecord, profile: DatasetProfile | None) -> dict[str, Any]:
    target_columns = target_columns_from_task(task)
    target_column = target_columns_display(target_columns) or (profile.target_column if profile else None)
    result: dict[str, Any] = {"status": "unavailable", "target_column": target_column}
    if not target_column:
        result["detail"] = "尚未确认目标列。"
        return result
    if len(target_columns) > 1:
        result["target_columns"] = target_columns
        result["detail"] = f"当前是多目标任务：{target_columns_display(target_columns)}，目标画像由 Codex 产物呈现。"
        return result

    sample = _collect_target_values(task, profile, target_column)
    if sample.detail:
        result["detail"] = sample.detail
        return result
    result["source"] = sample.source
    if not sample.values:
        result["detail"] = "目标列没有可分析的非空值。"
        result["scanned_rows"] = sample.scanned_rows
        return result

    result.update(_summarize_target_values(sample.values, scanned_rows=sample.scanned_rows))
    return result


def _collect_target_values(
    task: TaskRecord,
    profile: DatasetProfile | None,
    target_column: str,
) -> _TargetValueSample:
    file_sample = _TargetValueSample(values=[], scanned_rows=0, source="dataset_file")
    if task.dataset_path:
        file_sample = _read_dataset_target_values(Path(task.dataset_path), target_column)
        if file_sample.detail or file_sample.values:
            return file_sample
    if profile is not None and profile.preview_rows:
        preview_sample = _preview_target_values(profile, target_column)
        if preview_sample.values:
            return preview_sample
    return file_sample


def _read_dataset_target_values(dataset_path: Path, target_column: str) -> _TargetValueSample:
    values: list[str] = []
    scanned_rows = 0
    if not dataset_path.exists() or not dataset_path.is_file():
        return _TargetValueSample(values=[], scanned_rows=0, source="dataset_file")
    try:
        with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or target_column not in reader.fieldnames:
                return _TargetValueSample(
                    values=[],
                    scanned_rows=0,
                    source="dataset_file",
                    detail=f"CSV 表头中没有找到目标列 {target_column}。",
                )
            for index, row in enumerate(reader):
                if index >= MAX_TARGET_PROFILE_ROWS:
                    break
                scanned_rows += 1
                value = _clean_cell(row.get(target_column))
                if value:
                    values.append(value)
    except (OSError, csv.Error, UnicodeError) as exc:
        return _TargetValueSample(
            values=[],
            scanned_rows=0,
            source="dataset_file",
            detail=f"读取目标列失败：{exc}",
        )
    return _TargetValueSample(values=values, scanned_rows=scanned_rows, source="dataset_file")


def _preview_target_values(profile: DatasetProfile, target_column: str) -> _TargetValueSample:
    values: list[str] = []
    for row in profile.preview_rows:
        value = _clean_cell(row.get(target_column))
        if value:
            values.append(value)
    return _TargetValueSample(values=values, scanned_rows=len(profile.preview_rows), source="dataset_preview")


def _summarize_target_values(values: list[str], *, scanned_rows: int) -> dict[str, Any]:
    numeric_values = [_to_float(value) for value in values]
    numeric_clean = [value for value in numeric_values if value is not None]
    summary: dict[str, Any] = {
        "status": "available",
        "count": len(values),
        "scanned_rows": scanned_rows,
        "distinct_count": len(set(values)),
    }
    if len(numeric_clean) >= max(5, int(len(values) * 0.8)):
        summary.update(
            {
                "kind": "numeric",
                "numeric_count": len(numeric_clean),
                "mean": sum(numeric_clean) / len(numeric_clean),
                "std": _sample_std(numeric_clean),
                "min": min(numeric_clean),
                "q1": _quantile(numeric_clean, 0.25),
                "median": _quantile(numeric_clean, 0.5),
                "q3": _quantile(numeric_clean, 0.75),
                "max": max(numeric_clean),
            }
        )
        return summary

    distribution = Counter(values)
    total = sum(distribution.values()) or 1
    summary.update(
        {
            "kind": "categorical",
            "class_count": len(distribution),
            "top_values": [
                {"value": label, "count": count, "ratio": count / total}
                for label, count in distribution.most_common(10)
            ],
        }
    )
    return summary


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


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _quantile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
