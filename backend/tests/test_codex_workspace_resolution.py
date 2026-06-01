from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.models.task import RunAttempt, TaskRecord, TaskStatus
from backend.app.services.codex_backend import codex_plan_text, resolve_codex_workspace, sync_task_from_codex_artifacts
from backend.app.services.task_artifacts import build_run_artifact_index
from backend.app.services.task_code_workspace import build_task_code_workspace


def _task(task_id: str, dataset_path: Path) -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id=task_id,
        team_id="team-1",
        created_by="user-1",
        name="Task",
        description="Predict value",
        status=TaskStatus.completed,
        dataset_filename=dataset_path.name,
        dataset_path=str(dataset_path),
        executor_type="codex",
        codex_workspace_path=None,
        codex_started_at=None,
        created_at=now,
        updated_at=now,
    )


def _write_workspace_request(workspace: Path, *, task_id: str, dataset_path: Path | str) -> None:
    (workspace / "input").mkdir(parents=True)
    (workspace / "output").mkdir(exist_ok=True)
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({
            "authoritative_inputs": {
                "task_id": task_id,
                "data_path": str(dataset_path),
            },
        }),
        encoding="utf-8",
    )


def test_resolve_codex_workspace_uses_existing_explicit_candidate_without_manifest(tmp_path: Path) -> None:
    task_id = "explicit-workspace"
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    workspace = tmp_path / "manual-workspace"
    workspace.mkdir()

    task = _task(task_id, dataset_path)
    task.codex_workspace_path = str(workspace)
    settings = SimpleNamespace(codex_workspace_root=tmp_path / "missing-workspaces")

    assert resolve_codex_workspace(task, settings) == workspace


def test_resolve_codex_workspace_scans_latest_matching_workspace_started_after_task_start(tmp_path: Path) -> None:
    task_id = "scan-workspace"
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"
    older_workspace = workspace_root / "older"
    newer_workspace = workspace_root / "newer"
    _write_workspace_request(older_workspace, task_id=task_id, dataset_path=dataset_path)
    _write_workspace_request(newer_workspace, task_id=task_id, dataset_path=dataset_path)
    os.utime(older_workspace, (1_700_000_000, 1_700_000_000))
    os.utime(newer_workspace, (1_700_000_100, 1_700_000_100))

    task = _task(task_id, dataset_path)
    task.codex_started_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
    settings = SimpleNamespace(codex_workspace_root=workspace_root)

    assert resolve_codex_workspace(task, settings) == newer_workspace


def test_codex_plan_text_uses_deterministic_workspace_when_task_path_is_missing(tmp_path: Path) -> None:
    task_id = "10ab64fd"
    dataset_path = tmp_path / "storage" / "tasks" / task_id / "dataset.csv"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")

    workspace_root = tmp_path / "codex_use" / "workspaces"
    workspace = workspace_root / f"ai4ml-{task_id}"
    (workspace / "input").mkdir(parents=True)
    (workspace / "output").mkdir()
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({
            "authoritative_inputs": {
                "task_id": task_id,
                "data_path": str(dataset_path),
            },
        }),
        encoding="utf-8",
    )
    (workspace / "output" / "plan.md").write_text("# Plan\n\nRun this plan.", encoding="utf-8")

    task = _task(task_id, dataset_path)
    settings = SimpleNamespace(codex_workspace_root=workspace_root)

    assert resolve_codex_workspace(task, settings) == workspace
    assert codex_plan_text(task, settings) == "# Plan\n\nRun this plan."


def test_code_workspace_uses_deterministic_codex_workspace_when_record_path_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    task_id = "f7025790"
    dataset_path = tmp_path / "storage" / "tasks" / task_id / "dataset.csv"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")

    workspace_root = tmp_path / "codex_use" / "workspaces"
    workspace = workspace_root / f"ai4ml-{task_id}"
    (workspace / "input").mkdir(parents=True)
    (workspace / "output" / "code").mkdir(parents=True)
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({
            "authoritative_inputs": {
                "task_id": task_id,
                "data_path": str(dataset_path),
            },
        }),
        encoding="utf-8",
    )
    (workspace / "output" / "code" / "final_modeling.py").write_text("print('ok')\n", encoding="utf-8")

    task = _task(task_id, dataset_path)
    task.codex_workspace_path = r"D:\333\AI4ML\codex_use\workspaces\ai4ml-f7025790"
    task.last_run_attempt = RunAttempt(output_dir=r"D:\333\AI4ML\codex_use\workspaces\ai4ml-f7025790")
    settings = SimpleNamespace(codex_workspace_root=workspace_root, run_output_dir=tmp_path / "runs", repo_root=tmp_path)
    monkeypatch.setattr("backend.app.services.task_artifacts.get_settings", lambda: settings)

    artifact_index = build_run_artifact_index(task, settings=settings)
    assert artifact_index.output_dir == workspace

    code_workspace = build_task_code_workspace(task)
    assert code_workspace.run_output_dir == str(workspace)
    assert any(item.path == "output/code/final_modeling.py" for item in code_workspace.items)


def test_codex_sync_uses_local_dataset_when_record_path_is_stale(tmp_path: Path) -> None:
    task_id = "f7025790"
    storage_dir = tmp_path / "storage" / "tasks"
    dataset_path = storage_dir / task_id / "dataset.csv"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")

    workspace_root = tmp_path / "codex_use" / "workspaces"
    workspace = workspace_root / f"ai4ml-{task_id}"
    (workspace / "input").mkdir(parents=True)
    (workspace / "output").mkdir()
    (workspace / "input" / "task_request.json").write_text(
        json.dumps({
            "authoritative_inputs": {
                "task_id": task_id,
                "data_path": r"Z:\missing\AI4ML\storage\tasks\f7025790\dataset.csv",
            },
        }),
        encoding="utf-8",
    )
    (workspace / "output" / "progress.json").write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )

    task = _task(task_id, dataset_path)
    task.dataset_path = r"Z:\missing\AI4ML\storage\tasks\f7025790\dataset.csv"
    settings = SimpleNamespace(codex_workspace_root=workspace_root, storage_dir=storage_dir)

    synced_task, _artifacts = sync_task_from_codex_artifacts(task, settings)

    assert synced_task.dataset_path == str(dataset_path)
