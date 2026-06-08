from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_human_parameter_values import string_list
from backend.app.services.task_uploads import is_csv_upload_filename


def column_names(task: TaskRecord, requirements: dict[str, Any]) -> list[str]:
    for names in (
        _dataset_profile_column_names(task),
        _requirements_column_names(requirements),
        _requirements_profile_column_names(requirements),
        _dataset_header_column_names(task),
    ):
        if names:
            return names
    return []


def assert_known_columns(values: list[str], available_columns: list[str], label: str) -> None:
    if not available_columns:
        return
    unknown = [value for value in values if value not in available_columns]
    if unknown:
        raise RuntimeError(
            f"Unknown {label}: {', '.join(unknown)}. Available columns: {', '.join(available_columns)}"
        )


def _dataset_profile_column_names(task: TaskRecord) -> list[str]:
    if task.dataset_profile is None or not task.dataset_profile.columns:
        return []
    return [column.name for column in task.dataset_profile.columns]


def _requirements_column_names(requirements: dict[str, Any]) -> list[str]:
    return string_list(requirements.get("column_names"))


def _requirements_profile_column_names(requirements: dict[str, Any]) -> list[str]:
    profile = requirements.get("dataset_profile")
    if not isinstance(profile, dict):
        return []
    profile_columns = profile.get("columns")
    if not isinstance(profile_columns, list):
        return []
    names = [_profile_column_name(column) for column in profile_columns]
    return [name for name in names if name]


def _profile_column_name(column: object) -> str | None:
    if not isinstance(column, dict):
        return None
    name = str(column.get("name", "")).strip()
    return name or None


def _dataset_header_column_names(task: TaskRecord) -> list[str]:
    dataset_path = Path(task.dataset_path) if task.dataset_path else None
    if (
        not dataset_path
        or not dataset_path.exists()
        or not dataset_path.is_file()
        or not is_csv_upload_filename(dataset_path.name)
    ):
        return []
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return [str(item) for item in next(reader)]
        except StopIteration:
            return []
