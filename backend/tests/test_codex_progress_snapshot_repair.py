from __future__ import annotations

from backend.app.services.codex_progress_snapshot_repair import (
    repair_progress_snapshot_from_events,
    should_repair_progress_snapshot,
)
from backend.app.services.codex_progress_snapshot_values import coerce_percent, string_or_none


def test_snapshot_value_helpers_normalize_percent_and_strings() -> None:
    assert coerce_percent(None) is None
    assert coerce_percent("") is None
    assert coerce_percent("12.6") == 13
    assert coerce_percent("12.0") == 12
    assert coerce_percent("not-a-number") is None
    assert coerce_percent(float("inf")) is None
    assert string_or_none(" running ") == "running"
    assert string_or_none(" ") is None
    assert string_or_none(123) is None


def test_should_repair_progress_snapshot_requires_events_and_missing_percent() -> None:
    assert not should_repair_progress_snapshot({}, [])
    assert should_repair_progress_snapshot(None, [{"event": "training_started"}])
    assert should_repair_progress_snapshot({"status": "running"}, [{"event": "training_started"}])
    assert not should_repair_progress_snapshot({"progress_percent": 32}, [{"event": "training_started"}])
    assert not should_repair_progress_snapshot({"percent": "invalid"}, [])


def test_repair_progress_snapshot_preserves_current_text_and_steps_when_available() -> None:
    repaired = repair_progress_snapshot_from_events(
        {
            "status": "running",
            "current_step": "model_training",
            "summary": "Training selected model.",
            "updated_at": "2026-01-01T00:01:00+00:00",
            "steps": [{"id": "model_training", "status": "running"}],
        },
        {
            "status": "running",
            "current_step": "validation",
            "summary": "Validating.",
            "updated_at": "2026-01-01T00:02:00+00:00",
            "percent": 44,
            "percent_source": "event_percent",
            "steps": [{"id": "validation", "status": "pending"}],
        },
    )

    assert repaired["status"] == "running"
    assert repaired["current_step"] == "model_training"
    assert repaired["summary"] == "Training selected model."
    assert repaired["updated_at"] == "2026-01-01T00:01:00+00:00"
    assert repaired["steps"] == [{"id": "model_training", "status": "running"}]
    assert repaired["percent"] == 44
    assert repaired["percent_source"] == "event_percent"


def test_repair_progress_snapshot_clamps_noncompleted_terminal_percent() -> None:
    repaired = repair_progress_snapshot_from_events(
        {"status": "failed"},
        {
            "status": "failed",
            "updated_at": "2026-01-01T00:02:00+00:00",
            "percent": 150,
            "steps": [],
        },
    )

    assert repaired["status"] == "failed"
    assert repaired["percent"] == 99
    assert repaired["percent_source"] == "progress_event_percent"
    assert repaired["finished_at"] == "2026-01-01T00:02:00+00:00"


def test_repair_progress_snapshot_for_completed_sets_terminal_percent_and_finished_at() -> None:
    repaired = repair_progress_snapshot_from_events(
        {},
        {
            "status": "completed",
            "updated_at": "2026-01-01T00:02:00+00:00",
            "percent": 78,
            "finished_at": "2026-01-01T00:03:00+00:00",
            "steps": [],
        },
    )

    assert repaired["status"] == "completed"
    assert repaired["percent"] == 100
    assert repaired["percent_source"] == "completed"
    assert repaired["finished_at"] == "2026-01-01T00:03:00+00:00"
