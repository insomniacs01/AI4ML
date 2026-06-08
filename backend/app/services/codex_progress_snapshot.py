from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from backend.app.services.codex_progress_definitions import (
    PROGRESS_EVENTS_RELATIVE_PATH,
    PROGRESS_SCHEMA_VERSION,
    TERMINAL_STATUSES,
    progress_definition_value,
    progress_event_definition,
)
from backend.app.services.codex_progress_steps import build_progress_event_steps


def normalize_progress_event(payload: dict[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {
        "ts": _string_or_none(payload.get("ts")) or datetime.now(timezone.utc).isoformat(),
        "event": _string_or_none(payload.get("event")) or "progress_observed",
        "actor": _string_or_none(payload.get("actor")) or "ai4ml",
    }
    for key in ("status", "step", "current_step", "message", "summary", "percent_source"):
        value = _string_or_none(payload.get(key))
        if value:
            event[key] = value
    if payload.get("percent") is not None:
        event["percent"] = payload["percent"]
    if isinstance(payload.get("evidence"), list):
        event["evidence"] = [str(item).strip() for item in payload["evidence"] if str(item or "").strip()]
    if isinstance(payload.get("steps"), list):
        event["steps"] = payload["steps"]
    return event


def build_progress_snapshot(
    events: list[dict[str, Any]],
    *,
    previous_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous_progress if isinstance(previous_progress, dict) else {}
    percent = _coerce_percent(previous.get("percent", previous.get("progress_percent")))
    percent_source = (
        _string_or_none(previous.get("percent_source"))
        or _string_or_none(previous.get("progress_source"))
        or ("previous_progress_snapshot" if percent is not None else None)
    )
    status = _string_or_none(previous.get("status")) or "running"
    current_step = (
        _string_or_none(previous.get("current_step"))
        or _string_or_none(previous.get("currentStage"))
        or "workspace_initialized"
    )
    summary = _string_or_none(previous.get("summary")) or ""
    updated_at = _string_or_none(previous.get("updated_at")) or datetime.now(timezone.utc).isoformat()
    latest_steps = None

    ordered_events = [item for item in events if isinstance(item, dict)]
    for event in ordered_events:
        definition = progress_event_definition(event.get("event"))
        event_status = _string_or_none(event.get("status")) or progress_definition_value(definition, "status")
        event_step = (
            _string_or_none(event.get("step"))
            or _string_or_none(event.get("current_step"))
            or progress_definition_value(definition, "step")
        )
        event_summary = (
            _string_or_none(event.get("message"))
            or _string_or_none(event.get("summary"))
            or progress_definition_value(definition, "summary")
        )
        explicit_percent = _coerce_percent(event.get("percent")) if "percent" in event else None

        if event_status:
            status = event_status
        if event_step:
            current_step = event_step
        if event_summary:
            summary = event_summary
        if _string_or_none(event.get("ts")):
            updated_at = str(event["ts"])
        if isinstance(event.get("steps"), list):
            latest_steps = event["steps"]

        if explicit_percent is not None:
            previous_percent = percent
            if status == "completed":
                next_percent = 100
            else:
                next_percent = max(percent if percent is not None else 0, explicit_percent)
            advanced = previous_percent is None or next_percent > previous_percent or status == "completed"
            percent = next_percent
            if advanced:
                percent_source = _string_or_none(event.get("percent_source")) or "progress_event_percent"

    if status == "completed":
        percent = 100
        percent_source = "completed"
    elif status in {"failed", "cancelled", "interrupted"} and percent is not None:
        percent = min(99, max(0, percent))
    elif percent is not None:
        percent = min(99, max(0, percent))
    if percent_source == "workspace_initialized" and current_step != "workspace_initialized" and status != "completed":
        percent = None
        percent_source = None

    snapshot: dict[str, Any] = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "status": status,
        "current_step": current_step,
        "summary": summary,
        "updated_at": updated_at,
        "events_path": PROGRESS_EVENTS_RELATIVE_PATH,
        "steps": latest_steps if isinstance(latest_steps, list) else build_progress_event_steps(ordered_events),
    }
    if percent is not None:
        snapshot["percent"] = percent
        snapshot["percent_source"] = percent_source or "progress_event_percent"
    if status in TERMINAL_STATUSES:
        snapshot["finished_at"] = updated_at
    return snapshot


def should_repair_progress_snapshot(progress: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    if not events:
        return False
    if not isinstance(progress, dict):
        return True
    return _coerce_percent(progress.get("percent", progress.get("progress_percent"))) is None


def repair_progress_snapshot_from_events(progress: dict[str, Any], event_snapshot: dict[str, Any]) -> dict[str, Any]:
    current = progress if isinstance(progress, dict) else {}
    status = _string_or_none(current.get("status")) or _string_or_none(event_snapshot.get("status")) or "running"
    repaired: dict[str, Any] = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "status": status,
        "current_step": (
            _string_or_none(current.get("current_step"))
            or _string_or_none(event_snapshot.get("current_step"))
            or "workspace_initialized"
        ),
        "summary": _string_or_none(current.get("summary")) or _string_or_none(event_snapshot.get("summary")) or "",
        "updated_at": (
            _string_or_none(current.get("updated_at"))
            or _string_or_none(event_snapshot.get("updated_at"))
            or datetime.now(timezone.utc).isoformat()
        ),
        "events_path": PROGRESS_EVENTS_RELATIVE_PATH,
        "steps": current["steps"] if isinstance(current.get("steps"), list) and current["steps"] else event_snapshot.get("steps", []),
    }
    event_percent = _coerce_percent(event_snapshot.get("percent"))
    if status == "completed":
        repaired["percent"] = 100
        repaired["percent_source"] = "completed"
    elif event_percent is not None:
        repaired["percent"] = min(99, max(0, event_percent))
        repaired["percent_source"] = _string_or_none(event_snapshot.get("percent_source")) or "progress_event_percent"
    if event_snapshot.get("finished_at") or status in TERMINAL_STATUSES:
        repaired["finished_at"] = _string_or_none(event_snapshot.get("finished_at")) or repaired["updated_at"]
    return repaired


def _coerce_percent(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    if not numeric.is_integer():
        return round(numeric)
    return int(numeric)


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
