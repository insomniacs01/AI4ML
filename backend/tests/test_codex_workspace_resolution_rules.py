from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus
from backend.app.services.codex_workspace_resolution import (
    deterministic_workspace_for_task,
    resolve_codex_workspace_path,
    workspace_candidates,
    workspace_matches_task,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _task(task_id: str = "task-1", *, dataset_path: Path | None = None) -> TaskRecord:
    return TaskRecord(
        id=task_id,
        team_id="team-1",
        created_by="user-1",
        name="Workspace Resolution Task",
        description="Resolve Codex workspace.",
        status=TaskStatus.running,
        dataset_filename=dataset_path.name if dataset_path else None,
        dataset_path=str(dataset_path) if dataset_path else None,
        executor_type="codex",
        created_at=NOW,
        updated_at=NOW,
    )


def _settings(workspace_root: Path):
    return SimpleNamespace(codex_workspace_root=workspace_root)


def _write_request(workspace: Path, *, task_id: str | None = None, dataset_path: Path | str | None = None) -> None:
    authoritative_inputs = {}
    if task_id is not None:
        authoritative_inputs["task_id"] = task_id
    if dataset_path is not None:
        authoritative_inputs["data_path"] = str(dataset_path)
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({"authoritative_inputs": authoritative_inputs}),
        encoding="utf-8",
    )


def test_workspace_candidates_preserve_first_unique_path_across_task_sources(tmp_path: Path) -> None:
    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    third = str(tmp_path / "third")
    task = _task()
    task.codex_workspace_path = first
    task.last_run_attempt = RunAttempt(output_dir=second)
    task.last_run = RunSummary(best_model="ridge", metric_name="mae", metric_value=0.2, output_dir=first)
    task.structured_requirements = {"codex": {"workspace_path": third}}

    assert workspace_candidates(task) == [first, second, third]


def test_deterministic_workspace_for_task_sanitizes_task_id(tmp_path: Path) -> None:
    task = _task(" task/with:unsafe*chars-and-a-very-long-id-0123456789-abcdefghijklmnopqrstuvwxyz ")

    workspace = deterministic_workspace_for_task(task, _settings(tmp_path))

    assert workspace is not None
    assert workspace.parent == tmp_path
    assert workspace.name.startswith("ai4ml-task-with-unsafe-chars-and-a-very-long-id")
    assert len(workspace.name.removeprefix("ai4ml-")) == 64


def test_workspace_matches_task_uses_manifest_task_id_before_dataset_path(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    _write_request(workspace, task_id="different-task", dataset_path=dataset_path)

    assert not workspace_matches_task(workspace, _task("task-1", dataset_path=dataset_path))


def test_workspace_matches_task_falls_back_to_dataset_path_when_task_id_missing(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    _write_request(workspace, dataset_path=dataset_path)

    assert workspace_matches_task(workspace, _task("task-1", dataset_path=dataset_path))
    assert not workspace_matches_task(workspace, _task("task-1", dataset_path=tmp_path / "other.csv"))


def test_resolve_codex_workspace_prefers_existing_candidate_then_deterministic_then_latest_started(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    task = _task("task-1", dataset_path=dataset_path)

    explicit = tmp_path / "explicit"
    explicit.mkdir()
    task.codex_workspace_path = str(explicit)
    workspace_root = tmp_path / "workspaces"

    assert resolve_codex_workspace_path(task, _settings(workspace_root)) == explicit

    task.codex_workspace_path = str(tmp_path / "missing-explicit")
    deterministic = workspace_root / "ai4ml-task-1"
    _write_request(deterministic, task_id=task.id)

    assert resolve_codex_workspace_path(task, _settings(workspace_root)) == deterministic

    stale_match = workspace_root / "not-deterministic"
    deterministic.rename(stale_match)
    _write_request(stale_match, task_id="different-task")
    task.codex_started_at = datetime(2025, 12, 31, tzinfo=timezone.utc)
    older = workspace_root / "older"
    newer = workspace_root / "newer"
    _write_request(older, task_id=task.id)
    _write_request(newer, task_id=task.id)
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_100, 1_700_000_100))

    assert resolve_codex_workspace_path(task, _settings(workspace_root)) == newer
