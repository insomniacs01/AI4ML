from __future__ import annotations

from typing import Any

from backend.app.services.codex_progress_definitions import (
    progress_definition_value,
    progress_event_definition,
)


def build_progress_event_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        definition = progress_event_definition(event.get("event"))
        status = _string_or_none(event.get("status")) or progress_definition_value(definition, "status") or "running"
        latest = index == len(events) - 1
        steps.append(
            {
                "id": (
                    _string_or_none(event.get("step"))
                    or progress_definition_value(definition, "step")
                    or str(event.get("event") or f"event_{index + 1}")
                ),
                "title": progress_definition_value(definition, "title")
                or str(event.get("event") or f"进度事件 {index + 1}"),
                "status": _step_status_from_snapshot_status(status) if latest else "completed",
                "detail": _string_or_none(event.get("message"))
                or _string_or_none(event.get("summary"))
                or progress_definition_value(definition, "summary")
                or "",
                "updated_at": _string_or_none(event.get("ts")),
                "evidence": event.get("evidence") if isinstance(event.get("evidence"), list) else [],
            }
        )
    return steps


def _step_status_from_snapshot_status(status: str) -> str:
    if status == "completed":
        return "completed"
    if status == "interrupted":
        return "interrupted"
    if status in {"failed", "cancelled"}:
        return "failed"
    if status.startswith("waiting_") or status == "plan_ready":
        return "waiting_human"
    return "running"


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
