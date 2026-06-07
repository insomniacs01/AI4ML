from __future__ import annotations

from pathlib import Path

from backend.app.models.task import TaskRecord
from backend.app.services.task_runtime_resume import CODEX_IMPROVEMENT_REVIEW_STATUSES


def codex_stage_workspace_path(task: TaskRecord) -> str | None:
    return task.codex_workspace_path or (task.last_run_attempt.output_dir if task.last_run_attempt else None)


def codex_workspace_improvement_plan_path(task: TaskRecord, artifacts: dict | None = None) -> str | None:
    file_payload = artifacts.get("improvement_plan_file") if isinstance(artifacts, dict) else None
    if isinstance(file_payload, dict) and file_payload.get("exists") and isinstance(file_payload.get("path"), str):
        return file_payload["path"]
    workspace_path = codex_stage_workspace_path(task)
    if not workspace_path:
        return None
    plan_path = Path(workspace_path) / "output" / "improvement_plan.md"
    return str(plan_path) if plan_path.is_file() else None


def codex_improvement_plan_text(task: TaskRecord, artifacts: dict | None = None) -> str:
    if isinstance(artifacts, dict) and isinstance(artifacts.get("improvement_plan"), str):
        return artifacts["improvement_plan"]
    plan_path = codex_workspace_improvement_plan_path(task, artifacts)
    if not plan_path:
        return ""
    try:
        return Path(plan_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def has_codex_improvement_review(artifacts: dict | None) -> bool:
    if not isinstance(artifacts, dict):
        return False
    progress = artifacts.get("progress") if isinstance(artifacts.get("progress"), dict) else {}
    status_values = {
        str(progress.get("status") or "").strip().lower(),
        str(progress.get("current_step") or "").strip().lower(),
    }
    file_payload = artifacts.get("improvement_plan_file") if isinstance(artifacts.get("improvement_plan_file"), dict) else {}
    return bool(
        status_values & CODEX_IMPROVEMENT_REVIEW_STATUSES
        or isinstance(artifacts.get("improvement_plan"), str) and artifacts["improvement_plan"].strip()
        or file_payload.get("exists")
    )
