from __future__ import annotations

from urllib.parse import quote


TASK_SUMMARY_SELECT = ",".join(
    [
        "id",
        "team_id",
        "created_by",
        "creator_user_id",
        "name",
        "description",
        "workflow_id",
        "label_column",
        "problem_type",
        "status",
        "dataset_filename",
        "dataset_path",
        "notes",
        "executor_type",
        "codex_workspace_path",
        "codex_session_id",
        "codex_thread_id",
        "codex_status",
        "codex_started_at",
        "codex_finished_at",
        "routing_policy_id",
        "routing_source",
        "created_at",
        "updated_at",
    ]
)

TASK_LIST_SELECT = ",".join(
    [
        "id",
        "team_id",
        "created_by",
        "creator_user_id",
        "name",
        "description",
        "workflow_id",
        "label_column",
        "problem_type",
        "status",
        "dataset_filename",
        "dataset_path",
        "dataset_profile",
        "notes",
        "analysis_token_usage",
        "last_run",
        "last_run_attempt",
        "executor_type",
        "codex_workspace_path",
        "codex_session_id",
        "codex_thread_id",
        "codex_status",
        "codex_started_at",
        "codex_finished_at",
        "routing_policy_id",
        "routing_source",
        "structured_requirements",
        "stage_routing",
        "interaction_policies",
        "created_at",
        "updated_at",
    ]
)


def task_list_path(team_id: str, *, lightweight: bool, limit: int | None, offset: int) -> str:
    query_parts = [
        "ai_tasks",
        f"?select={TASK_SUMMARY_SELECT if lightweight else TASK_LIST_SELECT}",
        f"&team_id=eq.{quote(team_id, safe='')}",
        "&order=created_at.desc",
    ]
    if limit is not None:
        query_parts.append(f"&limit={max(1, min(int(limit), 500))}")
    if offset:
        query_parts.append(f"&offset={max(0, int(offset))}")
    return "".join(query_parts)


def task_detail_path(team_id: str, task_id: str) -> str:
    return (
        "ai_tasks"
        f"?select=*&team_id=eq.{quote(team_id, safe='')}"
        f"&id=eq.{quote(task_id, safe='')}"
        "&limit=1"
    )


def task_mutation_path(team_id: str, task_id: str) -> str:
    return (
        "ai_tasks"
        f"?team_id=eq.{quote(team_id, safe='')}"
        f"&id=eq.{quote(task_id, safe='')}"
    )
