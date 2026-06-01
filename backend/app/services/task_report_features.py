from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from backend.app.models.task import FeatureImportanceEntry, TaskRecord
from backend.app.services.task_artifacts import build_run_artifact_index

logger = logging.getLogger(__name__)


def codex_feature_importance(metrics: dict[str, Any], *, source: str) -> list[FeatureImportanceEntry]:
    selected = metrics.get("selected_model") if isinstance(metrics.get("selected_model"), dict) else {}
    raw = selected.get("feature_importance")
    if not isinstance(raw, dict):
        return []
    entries: list[FeatureImportanceEntry] = []
    for feature, value in raw.items():
        try:
            importance = float(value)
        except (TypeError, ValueError):
            continue
        if isinstance(feature, str) and feature.strip():
            entries.append(FeatureImportanceEntry(feature=feature.strip(), importance=importance, source=source))
    return sorted(entries, key=lambda item: abs(item.importance), reverse=True)[:20]


def collect_feature_importance(task: TaskRecord) -> tuple[list[FeatureImportanceEntry], list[str]]:
    artifact_index = build_run_artifact_index(task, prefer_success=True)
    if artifact_index.output_dir is None:
        return [], []

    entries: list[FeatureImportanceEntry] = []
    paths: list[str] = []
    for path in artifact_index.feature_importance_paths:
        parsed = parse_feature_importance_file(path)
        if parsed:
            entries.extend(parsed)
            paths.append(str(path))

    deduped: dict[str, FeatureImportanceEntry] = {}
    for entry in entries:
        current = deduped.get(entry.feature)
        if current is None or abs(entry.importance) > abs(current.importance):
            deduped[entry.feature] = entry

    return sorted(deduped.values(), key=lambda item: abs(item.importance), reverse=True)[:20], paths


def parse_feature_importance_file(path: Path) -> list[FeatureImportanceEntry]:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            return parse_feature_importance_payload(payload, source=str(path))
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return parse_feature_importance_payload(rows, source=str(path))
    except Exception as exc:
        logger.warning("Could not parse feature importance file %s: %s", path, exc)
        return []


def parse_feature_importance_payload(payload: Any, *, source: str) -> list[FeatureImportanceEntry]:
    rows = _feature_importance_rows(payload)
    if rows is None:
        return []

    entries: list[FeatureImportanceEntry] = []
    for row in rows:
        entry = _feature_importance_entry(row, source=source)
        if entry is not None:
            entries.append(entry)
    return entries


def _feature_importance_rows(payload: Any) -> list[Any] | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("feature_importance"), list):
            return payload["feature_importance"]
        if isinstance(payload.get("features"), list):
            return payload["features"]
        return [{"feature": key, "importance": value} for key, value in payload.items()]
    if isinstance(payload, list):
        return payload
    return None


def _feature_importance_entry(row: Any, *, source: str) -> FeatureImportanceEntry | None:
    if not isinstance(row, dict):
        return None
    feature = row.get("feature") or row.get("feature_name") or row.get("name") or row.get("column")
    importance = row.get("importance") or row.get("score") or row.get("value")
    try:
        numeric_importance = float(importance)
    except (TypeError, ValueError):
        return None
    if isinstance(feature, str) and feature.strip():
        return FeatureImportanceEntry(feature=feature.strip(), importance=numeric_importance, source=source)
    return None
