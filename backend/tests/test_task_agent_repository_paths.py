from __future__ import annotations

from backend.app.services.task_agent_repository_paths import (
    agent_events_path,
    agent_message_correlation_path,
    agent_messages_path,
    agent_run_lookup_path,
    agent_run_update_path,
    agent_runs_path,
)


def test_agent_run_paths_quote_identifiers() -> None:
    assert agent_runs_path("team/1", "task 1") == (
        "task_agent_runs?select=*&team_id=eq.team%2F1&task_id=eq.task%201&order=updated_at.desc"
    )
    assert agent_run_lookup_path("team/1", "task 1", "agent+1") == (
        "task_agent_runs?select=*&team_id=eq.team%2F1&task_id=eq.task%201"
        "&agent_id=eq.agent%2B1&order=updated_at.desc&limit=1"
    )
    assert agent_run_update_path("run/1") == "task_agent_runs?id=eq.run%2F1"


def test_agent_event_and_message_limits_are_clamped() -> None:
    assert agent_events_path("team", "task", limit=0).endswith("&limit=1")
    assert agent_events_path("team", "task", limit=500).endswith("&limit=200")
    assert agent_messages_path("team", "task", limit=0).endswith("&limit=1")
    assert agent_messages_path("team", "task", limit=500).endswith("&limit=300")


def test_agent_message_correlation_path_quotes_correlation_id() -> None:
    assert agent_message_correlation_path("team", "task", "agent-msg:data/a+b") == (
        "task_agent_messages?select=*&team_id=eq.team&task_id=eq.task"
        "&correlation_id=eq.agent-msg%3Adata%2Fa%2Bb&limit=1"
    )
