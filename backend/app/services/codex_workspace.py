from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord
from backend.app.services.codex_common import (
    as_utc,
    iso_from_mtime,
    latest_workspace_update,
    read_json,
    read_text,
)


class CodexWorkspaceReader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def read_artifacts(self, task: TaskRecord) -> dict[str, Any]:
        workspace = self.resolve(task)
        if workspace is None:
            return {"workspace": None}
        output_dir = workspace / "output"
        run_strategy_path = output_dir / "run_strategy.json"
        improvement_plan_path = output_dir / "improvement_plan.md"
        advisor_request_path = output_dir / "advisor_request.json"
        advisor_diagnosis_path = output_dir / "advisor_diagnosis.json"
        return {
            "workspace": {
                "name": workspace.name,
                "path": str(workspace),
                "modifiedAt": iso_from_mtime(workspace),
            },
            "plan": read_text(output_dir / "plan.md"),
            "run_strategy": read_json(run_strategy_path),
            "progress": read_json(output_dir / "progress.json"),
            "metrics": read_json(output_dir / "metrics.json"),
            "overview": read_json(output_dir / "overview.json"),
            "token_usage": read_json(output_dir / "token_usage.json"),
            "improvement_plan": read_text(improvement_plan_path),
            "advisor_request": read_json(advisor_request_path),
            "advisor_diagnosis": read_json(advisor_diagnosis_path),
            "run_strategy_file": {
                "path": str(run_strategy_path),
                "exists": run_strategy_path.is_file(),
            },
            "improvement_plan_file": {
                "path": str(improvement_plan_path),
                "exists": improvement_plan_path.is_file(),
                "modifiedAt": iso_from_mtime(improvement_plan_path) if improvement_plan_path.is_file() else None,
            },
            "advisor_request_file": {
                "path": str(advisor_request_path),
                "exists": advisor_request_path.is_file(),
            },
            "advisor_diagnosis_file": {
                "path": str(advisor_diagnosis_path),
                "exists": advisor_diagnosis_path.is_file(),
            },
            "overview_file": {
                "path": str(output_dir / "overview.json"),
                "exists": (output_dir / "overview.json").is_file(),
            },
            "report": {
                "path": str(output_dir / "report.md"),
                "exists": (output_dir / "report.md").is_file(),
            },
            "predict": {
                "path": str(output_dir / "predict.py"),
                "exists": (output_dir / "predict.py").is_file(),
            },
        }

    def resolve(self, task: TaskRecord) -> Path | None:
        candidate = _existing_candidate_workspace(task)
        if candidate is not None:
            return candidate

        deterministic_workspace = _matching_deterministic_workspace(task, self._settings)
        if deterministic_workspace is not None:
            return deterministic_workspace

        return _latest_started_workspace(task, self._settings)

    def plan_text(self, task: TaskRecord) -> str:
        artifacts = self.read_artifacts(task)
        plan = artifacts.get("plan")
        return plan if isinstance(plan, str) else ""

    def plan_path(self, task: TaskRecord) -> str | None:
        workspace = self.resolve(task)
        if workspace is None:
            return None
        plan_path = workspace / "output" / "plan.md"
        return str(plan_path) if plan_path.exists() else None


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


def _existing_candidate_workspace(task: TaskRecord) -> Path | None:
    for raw_path in workspace_candidates(task):
        path = Path(raw_path)
        if path.exists() and path.is_dir():
            return path
    return None


def _matching_deterministic_workspace(task: TaskRecord, settings: Settings) -> Path | None:
    workspace = deterministic_workspace_for_task(task, settings)
    if workspace is None or not workspace.exists() or not workspace.is_dir():
        return None
    return workspace if workspace_matches_task(workspace, task) else None


def _latest_started_workspace(task: TaskRecord, settings: Settings) -> Path | None:
    if task.codex_started_at is None:
        return None
    started_at = as_utc(task.codex_started_at)
    matching_directories = [
        path
        for path in _workspace_root_directories(settings.codex_workspace_root)
        if _workspace_updated_after(path, started_at) and workspace_matches_task(path, task)
    ]
    if not matching_directories:
        return None
    return sorted(matching_directories, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def _workspace_root_directories(root: Path) -> list[Path]:
    if not root.exists():
        return []
    try:
        return [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return []


def _workspace_updated_after(path: Path, started_at: datetime) -> bool:
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


def read_workspace_overview_artifacts(workspace: Path) -> dict[str, Any]:
    output_dir = workspace / "output"
    return {
        "workspace": {
            "name": workspace.name,
            "path": str(workspace),
            "modifiedAt": iso_from_mtime(workspace),
        },
        "metrics": read_json(output_dir / "metrics.json"),
        "overview": read_json(output_dir / "overview.json"),
        "overview_file": {
            "path": str(output_dir / "overview.json"),
            "exists": (output_dir / "overview.json").is_file(),
        },
    }
