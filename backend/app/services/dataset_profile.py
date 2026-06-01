from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetColumnProfile, DatasetProfile


MAX_PREVIEW_ROWS = 20
MAX_SAMPLE_VALUES_PER_COLUMN = 6
logger = logging.getLogger(__name__)


def build_dataset_profile(
    dataset_path: Path,
    *,
    filename: str | None = None,
    target_column: str | None = None,
) -> DatasetProfile:
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [str(item) for item in (reader.fieldnames or [])]
        trackers = {name: _ColumnTracker(name) for name in fieldnames}
        preview_rows: list[dict[str, str]] = []
        row_count = 0

        for row in reader:
            row_count += 1
            normalized_row = {
                name: "" if row.get(name) is None else str(row.get(name))
                for name in fieldnames
            }
            if len(preview_rows) < MAX_PREVIEW_ROWS:
                preview_rows.append({name: value[:200] for name, value in normalized_row.items()})
            for name, value in normalized_row.items():
                trackers[name].observe(value)

    return DatasetProfile(
        filename=filename or dataset_path.name,
        path=str(dataset_path),
        row_count=row_count,
        column_count=len(fieldnames),
        columns=[tracker.to_profile(row_count) for tracker in trackers.values()],
        preview_rows=preview_rows,
        target_column=target_column,
        generated_at=datetime.now(timezone.utc),
    )


def dataset_profile_to_plain(profile: DatasetProfile) -> dict[str, Any]:
    return profile.model_dump(mode="json")


def dataset_profile_from_plain(value: Any) -> DatasetProfile | None:
    if not isinstance(value, dict):
        return None
    try:
        return DatasetProfile.model_validate(value)
    except Exception as exc:
        logger.debug("Could not restore dataset profile from stored payload: %s", exc)
        return None


class _ColumnTracker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.non_empty_count = 0
        self.missing_count = 0
        self.type_hits: set[str] = set()
        self.samples: list[str] = []

    def observe(self, raw_value: str) -> None:
        value = raw_value.strip()
        if not value:
            self.missing_count += 1
            return
        self.non_empty_count += 1
        inferred = _infer_scalar_type(value)
        self.type_hits.add(inferred)
        if value not in self.samples and len(self.samples) < MAX_SAMPLE_VALUES_PER_COLUMN:
            self.samples.append(value[:120])

    def to_profile(self, row_count: int) -> DatasetColumnProfile:
        if self.non_empty_count == 0:
            inferred_type = "empty"
        else:
            typed_hits = self.type_hits - {"text"}
            if len(self.type_hits) == 1:
                inferred_type = next(iter(self.type_hits))
            elif self.type_hits <= {"integer", "number"}:
                inferred_type = "number"
            elif typed_hits and "text" not in self.type_hits:
                inferred_type = next(iter(typed_hits))
            else:
                inferred_type = "mixed"
        return DatasetColumnProfile(
            name=self.name,
            inferred_type=inferred_type,
            non_empty_count=self.non_empty_count,
            missing_count=self.missing_count,
            missing_ratio=(self.missing_count / row_count) if row_count else 0.0,
            sample_values=self.samples,
        )


def _infer_scalar_type(value: str) -> str:
    try:
        int(value)
        return "integer"
    except ValueError:
        pass

    try:
        float(value)
        return "number"
    except ValueError:
        pass

    normalized = value.replace("/", "-")
    for separator in ("T", " "):
        try:
            datetime.fromisoformat(normalized if separator in normalized else normalized)
            if "-" in normalized and any(char.isdigit() for char in normalized):
                return "datetime"
        except ValueError:
            continue

    return "text"
