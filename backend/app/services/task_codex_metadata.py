from __future__ import annotations

from backend.app.models.task import TaskRecord


def update_codex_structured_metadata(task: TaskRecord) -> TaskRecord:
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    codex = structured.get("codex") if isinstance(structured.get("codex"), dict) else {}
    structured["executor_type"] = "codex"
    structured["codex"] = {
        **codex,
        "workspace_path": task.codex_workspace_path,
        "session_id": task.codex_session_id,
        "thread_id": task.codex_thread_id,
        "status": task.codex_status,
        "started_at": task.codex_started_at.isoformat() if task.codex_started_at else None,
        "finished_at": task.codex_finished_at.isoformat() if task.codex_finished_at else None,
    }
    task.structured_requirements = structured
    return task
