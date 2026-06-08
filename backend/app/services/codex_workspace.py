from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord
from backend.app.services.codex_workspace_artifacts import (
    read_codex_workspace_artifacts,
    read_codex_workspace_overview_artifacts,
)
from backend.app.services.codex_workspace_resolution import resolve_codex_workspace_path


class CodexWorkspaceReader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def read_artifacts(self, task: TaskRecord) -> dict[str, Any]:
        workspace = self.resolve(task)
        if workspace is None:
            return {"workspace": None}
        return read_codex_workspace_artifacts(workspace)

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
    return read_codex_workspace_overview_artifacts(workspace)
