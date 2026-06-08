from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord
from backend.app.services.codex_common import (
    iso_from_mtime,
    read_json,
    read_text,
)
from backend.app.services.codex_progress_store import ensure_progress_snapshot, progress_events_path, read_progress_events
from backend.app.services.codex_workspace_resolution import resolve_codex_workspace_path


class CodexWorkspaceReader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def read_artifacts(self, task: TaskRecord) -> dict[str, Any]:
        workspace = self.resolve(task)
        if workspace is None:
            return {"workspace": None}
        output_dir = workspace / "output"
        progress_path = output_dir / "progress.json"
        run_strategy_path = output_dir / "run_strategy.json"
        improvement_plan_path = output_dir / "improvement_plan.md"
        advisor_request_path = output_dir / "advisor_request.json"
        advisor_diagnosis_path = output_dir / "advisor_diagnosis.json"
        progress_payload = ensure_progress_snapshot(workspace, current_progress=read_json(progress_path))
        events_path = progress_events_path(workspace)
        progress_events = read_progress_events(workspace)
        return {
            "workspace": {
                "name": workspace.name,
                "path": str(workspace),
                "modifiedAt": iso_from_mtime(workspace),
            },
            "plan": read_text(output_dir / "plan.md"),
            "run_strategy": read_json(run_strategy_path),
            "progress": progress_payload,
            "progress_events": progress_events,
            "progress_file": {
                "path": str(progress_path),
                "exists": progress_path.is_file(),
                "readable": progress_payload is not None,
            },
            "progress_events_file": {
                "path": str(events_path),
                "exists": events_path.is_file(),
                "readable": events_path.is_file(),
            },
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
        return resolve_codex_workspace_path(task, self._settings)

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
