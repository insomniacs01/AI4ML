from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetColumnProfile, DatasetProfile
from backend.app.services.tabular_numeric import parse_tabular_float


MAX_PREVIEW_ROWS = 20
MAX_SAMPLE_VALUES_PER_COLUMN = 6
MAX_PROFILE_ROWS = 1000
CSV_SNIFF_CHARS = 65536
logger = logging.getLogger(__name__)


def build_dataset_profile(
    dataset_path: Path,
    *,
    filename: str | None = None,
    target_column: str | None = None,
    max_profile_rows: int = MAX_PROFILE_ROWS,
) -> DatasetProfile:
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        sample = handle.read(CSV_SNIFF_CHARS)
        handle.seek(0)
        dialect = _detect_csv_dialect(sample)
        fast_row_count = _count_data_rows_fast(
            dataset_path,
            quotechar=getattr(dialect, "quotechar", None),
            sample=sample,
        )
        reader = csv.reader(handle, dialect)
        fieldnames = _named_columns(next(reader, []))
        trackers = {name: _ColumnTracker(name) for _, name in fieldnames}
        preview_rows: list[dict[str, str]] = []
        row_count = 0
        profiled_rows = 0
        profile_limit = max(0, max_profile_rows)
        rows_to_parse = max(MAX_PREVIEW_ROWS, profile_limit)

        for row in reader:
            if not _has_data(row):
                continue
            row_count += 1
            normalized_row = {
                name: _cell_value(row, index)
                for index, name in fieldnames
            }
            if len(preview_rows) < MAX_PREVIEW_ROWS:
                preview_rows.append({name: value[:200] for name, value in normalized_row.items()})
            if profiled_rows < profile_limit:
                profiled_rows += 1
                for name, value in normalized_row.items():
                    trackers[name].observe(value)
            if fast_row_count is not None and row_count >= rows_to_parse:
                break
        row_count = max(row_count, fast_row_count)

    return DatasetProfile(
        filename=filename or dataset_path.name,
        path=str(dataset_path),
        row_count=row_count,
        column_count=len(fieldnames),
        columns=[tracker.to_profile(profiled_rows) for tracker in trackers.values()],
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


def read_dataset_header(dataset_path: Path) -> list[str]:
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        sample = handle.read(CSV_SNIFF_CHARS)
        handle.seek(0)
        reader = csv.reader(handle, _detect_csv_dialect(sample))
        return [name for _, name in _named_columns(next(reader, []))]


def read_dataset_rows(dataset_path: Path, *, max_rows: int | None = None) -> tuple[list[str], list[dict[str, str]]]:
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        sample = handle.read(CSV_SNIFF_CHARS)
        handle.seek(0)
        reader = csv.reader(handle, _detect_csv_dialect(sample))
        fieldnames = _named_columns(next(reader, []))
        rows: list[dict[str, str]] = []
        for row in reader:
            if not _has_data(row):
                continue
            rows.append({name: _cell_value(row, index) for index, name in fieldnames})
            if max_rows is not None and len(rows) >= max_rows:
                break
    return [name for _, name in fieldnames], rows


def _detect_csv_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def _count_data_rows_fast(dataset_path: Path, *, quotechar: str | None, sample: str) -> int:
    if not _sample_has_quoted_newline(sample, quotechar=quotechar):
        return _count_physical_data_rows(dataset_path)
    quote_byte = (quotechar or '"').encode("utf-8", errors="ignore")[:1] or b'"'
    quote = quote_byte[0]
    records = 0
    in_quotes = False
    record_has_data = False
    previous_was_cr = False
    with dataset_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            for byte in chunk:
                if byte == quote:
                    in_quotes = not in_quotes
                    record_has_data = True
                    previous_was_cr = False
                    continue
                if not in_quotes and byte in (10, 13):
                    if byte == 10 and previous_was_cr:
                        previous_was_cr = False
                        continue
                    if record_has_data:
                        records += 1
                    record_has_data = False
                    previous_was_cr = byte == 13
                    continue
                previous_was_cr = False
                if byte not in (9, 32):
                    record_has_data = True
    if record_has_data:
        records += 1
    return max(0, records - 1)


def _count_physical_data_rows(dataset_path: Path) -> int:
    count = 0
    with dataset_path.open("rb") as handle:
        for line_number, line in enumerate(handle):
            if line_number == 0:
                continue
            if line.strip():
                count += 1
    return count


def _sample_has_quoted_newline(sample: str, *, quotechar: str | None) -> bool:
    quote = quotechar or '"'
    in_quotes = False
    for char in sample:
        if char == quote:
            in_quotes = not in_quotes
            continue
        if in_quotes and char in "\r\n":
            return True
    return False


def _named_columns(header: list[str]) -> list[tuple[int, str]]:
    columns: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    for index, raw_name in enumerate(header):
        name = str(raw_name or "").strip()
        if not name:
            continue
        count = seen.get(name, 0) + 1
        seen[name] = count
        columns.append((index, name if count == 1 else f"{name}_{count}"))
    return columns


def _has_data(row: list[str]) -> bool:
    return any(str(cell or "").strip() for cell in row)


def _cell_value(row: list[str], index: int) -> str:
    return "" if index >= len(row) else str(row[index] or "")


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

    if parse_tabular_float(value) is not None:
        return "number"

    normalized = value.replace("/", "-")
    if _is_common_date(value):
        return "datetime"
    for separator in ("T", " "):
        try:
            datetime.fromisoformat(normalized if separator in normalized else normalized)
            if "-" in normalized and any(char.isdigit() for char in normalized):
                return "datetime"
        except ValueError:
            continue

    return "text"


def _is_common_date(value: str) -> bool:
    text = value.strip()
    for date_format in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            datetime.strptime(text, date_format)
            return True
        except ValueError:
            continue
    return False
