from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord
from backend.app.services.codex_common import as_utc, latest_workspace_update, read_json


def resolve_codex_workspace_path(task: TaskRecord, settings: Settings) -> Path | None:
    candidate = existing_candidate_workspace(task)
    if candidate is not None:
        return candidate

    deterministic_workspace = matching_deterministic_workspace(task, settings)
    if deterministic_workspace is not None:
        return deterministic_workspace

    return latest_started_workspace(task, settings)


def workspace_candidates(task: TaskRecord) -> list[str]:
    candidates = []
    if task.codex_workspace_path:
        candidates.append(task.codex_workspace_path)
    if task.last_run_attempt and task.last_run_attempt.output_dir:
        candidates.append(task.last_run_attempt.output_dir)
    if task.last_run and task.last_run.output_dir:
        candidates.append(task.last_run.output_dir)
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    codex = structured.get("codex") if isinstance(structured.get("codex"), dict) else {}
    path_value = codex.get("workspace_path")
    if isinstance(path_value, str) and path_value:
        candidates.append(path_value)
    seen: set[str] = set()
    unique: list[str] = []
    for value in candidates:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def existing_candidate_workspace(task: TaskRecord) -> Path | None:
    for raw_path in workspace_candidates(task):
        path = Path(raw_path)
        if path.exists() and path.is_dir():
            return path
    return None


def matching_deterministic_workspace(task: TaskRecord, settings: Settings) -> Path | None:
    workspace = deterministic_workspace_for_task(task, settings)
    if workspace is None or not workspace.exists() or not workspace.is_dir():
        return None
    return workspace if workspace_matches_task(workspace, task) else None


def latest_started_workspace(task: TaskRecord, settings: Settings) -> Path | None:
    if task.codex_started_at is None:
        return None
    started_at = as_utc(task.codex_started_at)
    matching_directories = [
        path
        for path in workspace_root_directories(settings.codex_workspace_root)
        if workspace_updated_after(path, started_at) and workspace_matches_task(path, task)
    ]
    if not matching_directories:
        return None
    return sorted(matching_directories, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def workspace_root_directories(root: Path) -> list[Path]:
    if not root.exists():
        return []
    try:
        return [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return []


def workspace_updated_after(path: Path, started_at: datetime) -> bool:
    updated_at = latest_workspace_update(path)
    return updated_at is not None and updated_at >= started_at


def deterministic_workspace_for_task(task: TaskRecord, settings: Settings) -> Path | None:
    safe_task_id = "".join(
        char if char.isalnum() or char in {"_", "-"} else "-"
        for char in task.id.strip()
    )[:64]
    if not safe_task_id:
        return None
    return settings.codex_workspace_root / f"ai4ml-{safe_task_id}"


def workspace_matches_task(workspace: Path, task: TaskRecord) -> bool:
    request_payload = read_json(workspace / "input" / "task_request.json")
    if not isinstance(request_payload, dict):
        return False
    authoritative_inputs = request_payload.get("authoritative_inputs")
    if not isinstance(authoritative_inputs, dict):
        return False
    request_task_id = authoritative_inputs.get("task_id")
    if isinstance(request_task_id, str) and request_task_id:
        return request_task_id == task.id
    data_path = authoritative_inputs.get("data_path")
    if not isinstance(data_path, str) or not task.dataset_path:
        return False
    try:
        return Path(data_path).resolve() == Path(task.dataset_path).resolve()
    except OSError:
        return data_path == task.dataset_path
