from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.services.codex_progress_definitions import (
    PROGRESS_EVENTS_RELATIVE_PATH,
    PROGRESS_SCHEMA_VERSION,
    TERMINAL_STATUSES,
)
from backend.app.services.codex_progress_snapshot_values import coerce_percent, string_or_none


def should_repair_progress_snapshot(progress: Any, events: list[dict[str, Any]]) -> bool:
    if not events:
        return False
    if not isinstance(progress, dict):
        return True
    return coerce_percent(progress.get("percent", progress.get("progress_percent"))) is None


def repair_progress_snapshot_from_events(progress: Any, event_snapshot: dict[str, Any]) -> dict[str, Any]:
    current = progress if isinstance(progress, dict) else {}
    status = string_or_none(current.get("status")) or string_or_none(event_snapshot.get("status")) or "running"
    repaired: dict[str, Any] = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "status": status,
        "current_step": (
            string_or_none(current.get("current_step"))
            or string_or_none(event_snapshot.get("current_step"))
            or "workspace_initialized"
        ),
        "summary": string_or_none(current.get("summary")) or string_or_none(event_snapshot.get("summary")) or "",
        "updated_at": (
            string_or_none(current.get("updated_at"))
            or string_or_none(event_snapshot.get("updated_at"))
            or datetime.now(timezone.utc).isoformat()
        ),
        "events_path": PROGRESS_EVENTS_RELATIVE_PATH,
        "steps": current["steps"] if isinstance(current.get("steps"), list) and current["steps"] else event_snapshot.get("steps", []),
    }
    event_percent = coerce_percent(event_snapshot.get("percent"))
    if status == "completed":
        repaired["percent"] = 100
        repaired["percent_source"] = "completed"
    elif event_percent is not None:
        repaired["percent"] = min(99, max(0, event_percent))
        repaired["percent_source"] = string_or_none(event_snapshot.get("percent_source")) or "progress_event_percent"
    if event_snapshot.get("finished_at") or status in TERMINAL_STATUSES:
        repaired["finished_at"] = string_or_none(event_snapshot.get("finished_at")) or repaired["updated_at"]
    return repaired
