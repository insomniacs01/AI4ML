from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.app.services.codex_progress_definitions import (
    PROGRESS_EVENTS_RELATIVE_PATH,
    PROGRESS_SCHEMA_VERSION,
    TERMINAL_STATUSES,
    progress_definition_value,
    progress_event_definition,
)
from backend.app.services.codex_progress_snapshot_values import coerce_percent, string_or_none
from backend.app.services.codex_progress_steps import build_progress_event_steps


@dataclass
class _ProgressSnapshotState:
    percent: int | None
    percent_source: str | None
    status: str
    current_step: str
    summary: str
    updated_at: str
    latest_steps: list[Any] | None = None


def normalize_progress_event(payload: dict[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {
        "ts": string_or_none(payload.get("ts")) or datetime.now(timezone.utc).isoformat(),
        "event": string_or_none(payload.get("event")) or "progress_observed",
        "actor": string_or_none(payload.get("actor")) or "ai4ml",
    }
    for key in ("status", "step", "current_step", "message", "summary", "percent_source"):
        value = string_or_none(payload.get(key))
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
    ordered_events = _ordered_progress_events(events)
    state = _initial_progress_state(previous_progress)
    for event in ordered_events:
        _apply_progress_event(state, event)
    _normalize_final_percent(state)
    return _snapshot_payload(state, ordered_events)


def _ordered_progress_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in events if isinstance(item, dict)]


def _initial_progress_state(previous_progress: dict[str, Any] | None) -> _ProgressSnapshotState:
    previous = previous_progress if isinstance(previous_progress, dict) else {}
    percent = coerce_percent(previous.get("percent", previous.get("progress_percent")))
    percent_source = (
        string_or_none(previous.get("percent_source"))
        or string_or_none(previous.get("progress_source"))
        or ("previous_progress_snapshot" if percent is not None else None)
    )
    status = string_or_none(previous.get("status")) or "running"
    current_step = (
        string_or_none(previous.get("current_step"))
        or string_or_none(previous.get("currentStage"))
        or "workspace_initialized"
    )
    return _ProgressSnapshotState(
        percent=percent,
        percent_source=percent_source,
        status=status,
        current_step=current_step,
        summary=string_or_none(previous.get("summary")) or "",
        updated_at=string_or_none(previous.get("updated_at")) or datetime.now(timezone.utc).isoformat(),
    )


def _apply_progress_event(state: _ProgressSnapshotState, event: dict[str, Any]) -> None:
    definition = progress_event_definition(event.get("event"))
    event_status = string_or_none(event.get("status")) or progress_definition_value(definition, "status")
    event_step = (
        string_or_none(event.get("step"))
        or string_or_none(event.get("current_step"))
        or progress_definition_value(definition, "step")
    )
    event_summary = (
        string_or_none(event.get("message"))
        or string_or_none(event.get("summary"))
        or progress_definition_value(definition, "summary")
    )

    if event_status:
        state.status = event_status
    if event_step:
        state.current_step = event_step
    if event_summary:
        state.summary = event_summary
    if string_or_none(event.get("ts")):
        state.updated_at = str(event["ts"])
    if isinstance(event.get("steps"), list):
        state.latest_steps = event["steps"]
    if "percent" in event:
        _apply_event_percent(state, event)


def _apply_event_percent(state: _ProgressSnapshotState, event: dict[str, Any]) -> None:
    explicit_percent = coerce_percent(event.get("percent"))
    if explicit_percent is None:
        return

    previous_percent = state.percent
    if state.status == "completed":
        next_percent = 100
    else:
        next_percent = max(state.percent if state.percent is not None else 0, explicit_percent)
    advanced = previous_percent is None or next_percent > previous_percent or state.status == "completed"
    state.percent = next_percent
    if advanced:
        state.percent_source = string_or_none(event.get("percent_source")) or "progress_event_percent"


def _normalize_final_percent(state: _ProgressSnapshotState) -> None:
    if state.status == "completed":
        state.percent = 100
        state.percent_source = "completed"
    elif state.status in {"failed", "cancelled", "interrupted"} and state.percent is not None:
        state.percent = min(99, max(0, state.percent))
    elif state.percent is not None:
        state.percent = min(99, max(0, state.percent))
    if (
        state.percent_source == "workspace_initialized"
        and state.current_step != "workspace_initialized"
        and state.status != "completed"
    ):
        state.percent = None
        state.percent_source = None


def _snapshot_payload(state: _ProgressSnapshotState, ordered_events: list[dict[str, Any]]) -> dict[str, Any]:
    steps = state.latest_steps if isinstance(state.latest_steps, list) else build_progress_event_steps(ordered_events)
    snapshot: dict[str, Any] = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        "status": state.status,
        "current_step": state.current_step,
        "summary": state.summary,
        "updated_at": state.updated_at,
        "events_path": PROGRESS_EVENTS_RELATIVE_PATH,
        "steps": steps,
    }
    if state.percent is not None:
        snapshot["percent"] = state.percent
        snapshot["percent_source"] = state.percent_source or "progress_event_percent"
    if state.status in TERMINAL_STATUSES:
        snapshot["finished_at"] = state.updated_at
    return snapshot
