from __future__ import annotations

from urllib.parse import quote


def agent_runs_path(team_id: str, task_id: str) -> str:
    return (
        "task_agent_runs"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&task_id=eq.{quote(task_id, safe='')}"
        "&order=updated_at.desc"
    )


def agent_run_lookup_path(team_id: str, task_id: str, agent_id: str) -> str:
    return (
        "task_agent_runs"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&task_id=eq.{quote(task_id, safe='')}"
        f"&agent_id=eq.{quote(agent_id, safe='')}"
        "&order=updated_at.desc"
        "&limit=1"
    )


def agent_run_update_path(run_id: str) -> str:
    return f"task_agent_runs?id=eq.{quote(run_id, safe='')}"


def agent_events_path(team_id: str, task_id: str, *, limit: int) -> str:
    return (
        "task_agent_events"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&task_id=eq.{quote(task_id, safe='')}"
        "&order=created_at.desc"
        f"&limit={_clamp(limit, minimum=1, maximum=200)}"
    )


def agent_messages_path(team_id: str, task_id: str, *, limit: int) -> str:
    return (
        "task_agent_messages"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&task_id=eq.{quote(task_id, safe='')}"
        "&order=created_at.desc"
        f"&limit={_clamp(limit, minimum=1, maximum=300)}"
    )


def agent_message_correlation_path(team_id: str, task_id: str, correlation_id: str) -> str:
    return (
        "task_agent_messages"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&task_id=eq.{quote(task_id, safe='')}"
        f"&correlation_id=eq.{quote(correlation_id, safe='')}"
        "&limit=1"
    )


def _clamp(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))
