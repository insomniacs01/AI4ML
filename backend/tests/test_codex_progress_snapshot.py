from __future__ import annotations

from backend.app.services.codex_progress_snapshot import (
    build_progress_snapshot,
    normalize_progress_event,
)
from backend.app.services.codex_progress_snapshot_repair import (
    repair_progress_snapshot_from_events,
    should_repair_progress_snapshot,
)


def test_build_progress_snapshot_uses_event_definitions_for_status_and_steps() -> None:
    events = [
        normalize_progress_event(
            {
                "event": "workspace_initialized",
                "actor": "codex",
                "percent": 1,
                "percent_source": "workspace_initialized",
                "ts": "2026-01-01T00:00:00+00:00",
            }
        ),
        normalize_progress_event(
            {
                "event": "plan_generated",
                "actor": "codex",
                "evidence": [" output/plan.md ", ""],
                "ts": "2026-01-01T00:01:00+00:00",
            }
        ),
    ]

    snapshot = build_progress_snapshot(events)

    assert snapshot["status"] == "waiting_plan_approval"
    assert snapshot["current_step"] == "waiting_plan_approval"
    assert snapshot["summary"] == "Codex 已生成执行计划，等待用户确认。"
    assert "percent" not in snapshot
    assert snapshot["steps"][0]["status"] == "completed"
    assert snapshot["steps"][1]["status"] == "waiting_human"
    assert snapshot["steps"][1]["evidence"] == ["output/plan.md"]


def test_completed_snapshot_and_repair_payload_keep_terminal_percent() -> None:
    event_snapshot = build_progress_snapshot(
        [
            normalize_progress_event(
                {
                    "event": "completed",
                    "actor": "codex",
                    "percent": 78,
                    "ts": "2026-01-01T00:02:00+00:00",
                }
            )
        ]
    )

    assert event_snapshot["status"] == "completed"
    assert event_snapshot["percent"] == 100
    assert event_snapshot["percent_source"] == "completed"
    assert event_snapshot["finished_at"] == "2026-01-01T00:02:00+00:00"
    assert should_repair_progress_snapshot({"status": "completed"}, [{"event": "completed"}])

    repaired = repair_progress_snapshot_from_events({}, event_snapshot)

    assert repaired["status"] == "completed"
    assert repaired["percent"] == 100
    assert repaired["percent_source"] == "completed"
    assert repaired["finished_at"] == "2026-01-01T00:02:00+00:00"
