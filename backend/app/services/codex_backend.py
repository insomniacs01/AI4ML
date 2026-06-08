from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.models.task import (
    TaskRecord,
    TaskRunProgressResponse,
)
from backend.app.services.codex_common import CodexBackendError
from backend.app.services.codex_http import CodexBackendClient
from backend.app.services.codex_progress import build_codex_run_progress_response
from backend.app.services.codex_overview import build_codex_overview_from_artifacts
from backend.app.services.codex_task_artifact_sync import apply_codex_artifact_sync
from backend.app.services.codex_workspace import CodexWorkspaceReader, read_workspace_overview_artifacts


def start_codex_task(task: TaskRecord, settings: Settings, *, token_budget: int | None = None) -> dict[str, Any]:
    return CodexBackendClient(settings).start_task(task, token_budget=token_budget)


def approve_codex_plan(
    task: TaskRecord,
    settings: Settings,
    *,
    plan_text: str,
    token_budget: int | None = None,
) -> dict[str, Any]:
    return CodexBackendClient(settings).approve_plan(task, plan_text=plan_text, token_budget=token_budget)


def regenerate_codex_plan(task: TaskRecord, settings: Settings, *, token_budget: int | None = None) -> dict[str, Any]:
    return CodexBackendClient(settings).regenerate_plan(task, token_budget=token_budget)


def interrupt_codex_task(task: TaskRecord, settings: Settings, *, reason: str | None = None) -> dict[str, Any]:
    return CodexBackendClient(settings).interrupt_task(task, reason=reason)


def resume_codex_task(
    task: TaskRecord,
    settings: Settings,
    *,
    token_budget: int | None = None,
    improvement_decision: str | None = None,
) -> dict[str, Any]:
    return CodexBackendClient(settings).resume_task(
        task,
        token_budget=token_budget,
        improvement_decision=improvement_decision,
    )


def fetch_codex_task_status(task: TaskRecord, settings: Settings) -> dict[str, Any]:
    return CodexBackendClient(settings).task_status(task)


def fetch_latest_codex_artifacts(settings: Settings) -> dict[str, Any]:
    return CodexBackendClient(settings).fetch_latest_artifacts()


def reload_codex_config(settings: Settings) -> dict[str, Any]:
    return CodexBackendClient(settings).reload_config()


def read_codex_artifacts(task: TaskRecord, settings: Settings) -> dict[str, Any]:
    return CodexWorkspaceReader(settings).read_artifacts(task)


def build_codex_overview(task: TaskRecord, settings: Settings) -> dict[str, Any]:
    return build_codex_overview_from_artifacts(read_codex_artifacts(task, settings))


def build_codex_overview_from_workspace(workspace: Path) -> dict[str, Any]:
    return build_codex_overview_from_artifacts(read_workspace_overview_artifacts(workspace))


def resolve_codex_workspace(task: TaskRecord, settings: Settings) -> Path | None:
    return CodexWorkspaceReader(settings).resolve(task)


def build_codex_run_progress(task: TaskRecord, settings: Settings) -> TaskRunProgressResponse:
    artifacts = read_codex_artifacts(task, settings)
    return build_codex_run_progress_response(task, artifacts)


def sync_task_from_codex_artifacts(task: TaskRecord, settings: Settings) -> tuple[TaskRecord, dict[str, Any]]:
    _sync_dataset_path_from_local_storage(task, settings)
    artifacts = read_codex_artifacts(task, settings)
    return apply_codex_artifact_sync(task, artifacts), artifacts


def codex_plan_text(task: TaskRecord, settings: Settings) -> str:
    return CodexWorkspaceReader(settings).plan_text(task)


def codex_workspace_plan_path(task: TaskRecord, settings: Settings) -> str | None:
    return CodexWorkspaceReader(settings).plan_path(task)


def _sync_dataset_path_from_local_storage(task: TaskRecord, settings: Settings) -> None:
    if task.dataset_path and Path(task.dataset_path).exists():
        return
    dataset_dir = settings.storage_dir / task.id / "dataset"
    if dataset_dir.is_dir():
        task.dataset_path = str(dataset_dir)
        if not task.dataset_filename:
            try:
                first_file = next(path for path in dataset_dir.iterdir() if path.is_file())
            except (OSError, StopIteration):
                first_file = None
            if first_file is not None:
                task.dataset_filename = first_file.name
        return
    candidate = settings.storage_dir / task.id / "dataset.csv"
    if not candidate.is_file():
        return
    task.dataset_path = str(candidate)
    if not task.dataset_filename:
        task.dataset_filename = candidate.name
