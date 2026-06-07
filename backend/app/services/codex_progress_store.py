from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.services.codex_progress_snapshot import (
    PROGRESS_EVENTS_RELATIVE_PATH,
    build_progress_snapshot,
    normalize_progress_event,
    repair_progress_snapshot_from_events,
    should_repair_progress_snapshot,
)


PROGRESS_SNAPSHOT_RELATIVE_PATH = "output/progress.json"


def append_progress_event(
    workspace_path: str | Path,
    event: str,
    *,
    actor: str = "ai4ml_backend",
    status: str | None = None,
    step: str | None = None,
    message: str | None = None,
    percent: Any = None,
    percent_source: str | None = None,
    evidence: list[str] | None = None,
    steps: list[dict[str, Any]] | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace_path)
    event_payload = normalize_progress_event(
        {
            "event": event,
            "actor": actor,
            "status": status,
            "step": step,
            "message": message,
            "percent": percent,
            "percent_source": percent_source,
            "evidence": evidence,
            "steps": steps,
            "ts": (timestamp or datetime.now(timezone.utc)).isoformat(),
        }
    )
    events = read_progress_events(workspace)
    previous_progress = _read_progress_snapshot(workspace)
    snapshot = build_progress_snapshot([*events, event_payload], previous_progress=previous_progress)

    event_path = progress_events_path(workspace)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{json.dumps(event_payload, ensure_ascii=False, separators=(',', ':'))}\n")
    _write_progress_snapshot(workspace, snapshot)
    return snapshot


def ensure_progress_snapshot(
    workspace_path: str | Path,
    *,
    current_progress: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    workspace = Path(workspace_path)
    has_current_progress = isinstance(current_progress, dict)
    current = current_progress if has_current_progress else _read_progress_snapshot(workspace)
    events = read_progress_events(workspace)
    if not should_repair_progress_snapshot(current, events):
        if has_current_progress:
            return current_progress
        return current if current else None
    event_snapshot = build_progress_snapshot(events, previous_progress=None)
    repaired = repair_progress_snapshot_from_events(current, event_snapshot)
    _write_progress_snapshot(workspace, repaired)
    return repaired


def read_progress_events(workspace_path: str | Path) -> list[dict[str, Any]]:
    path = progress_events_path(workspace_path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    events: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def progress_events_path(workspace_path: str | Path) -> Path:
    return Path(workspace_path) / PROGRESS_EVENTS_RELATIVE_PATH


def progress_snapshot_path(workspace_path: str | Path) -> Path:
    return Path(workspace_path) / PROGRESS_SNAPSHOT_RELATIVE_PATH


def _read_progress_snapshot(workspace_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(progress_snapshot_path(workspace_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_progress_snapshot(workspace_path: Path, snapshot: dict[str, Any]) -> None:
    path = progress_snapshot_path(workspace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.{id(snapshot)}.tmp")
    content = f"{json.dumps(snapshot, ensure_ascii=False, indent=2)}\n"
    temporary_path.write_text(content, encoding="utf-8")
    _replace_progress_file(temporary_path, path, content)


def _replace_progress_file(temporary_path: Path, target_path: Path, content: str) -> None:
    for attempt in range(5):
        try:
            temporary_path.replace(target_path)
            return
        except PermissionError:
            if attempt == 4:
                target_path.write_text(content, encoding="utf-8")
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
                return
        time.sleep(0.02 * (attempt + 1))
