from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.codex_workspace_artifacts import (
    file_status,
    read_codex_workspace_artifacts,
    read_codex_workspace_overview_artifacts,
)


def test_read_codex_workspace_artifacts_projects_files_and_payloads(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output_dir = workspace / "output"
    state_dir = workspace / "state"
    output_dir.mkdir(parents=True)
    state_dir.mkdir()
    (output_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (output_dir / "metrics.json").write_text(json.dumps({"score": 0.9}), encoding="utf-8")
    (output_dir / "overview.json").write_text(json.dumps({"best_model": "ridge"}), encoding="utf-8")
    (output_dir / "progress.json").write_text(json.dumps({"status": "running", "percent": 42}), encoding="utf-8")
    (output_dir / "improvement_plan.md").write_text("Improve features.", encoding="utf-8")
    (output_dir / "predict.py").write_text("print('predict')\n", encoding="utf-8")
    (state_dir / "progress_events.jsonl").write_text(
        json.dumps({"event": "modeling_started"}) + "\n",
        encoding="utf-8",
    )

    artifacts = read_codex_workspace_artifacts(workspace)

    assert artifacts["workspace"]["name"] == "workspace"
    assert artifacts["plan"] == "# Plan\n"
    assert artifacts["metrics"] == {"score": 0.9}
    assert artifacts["overview"] == {"best_model": "ridge"}
    assert artifacts["progress"] == {"status": "running", "percent": 42}
    assert artifacts["progress_events"] == [{"event": "modeling_started"}]
    assert artifacts["progress_file"]["readable"] is True
    assert artifacts["improvement_plan_file"]["exists"] is True
    assert artifacts["improvement_plan_file"]["modifiedAt"] is not None
    assert artifacts["predict"]["exists"] is True
    assert artifacts["report"]["exists"] is False


def test_read_codex_workspace_overview_artifacts_uses_same_workspace_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "overview.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

    artifacts = read_codex_workspace_overview_artifacts(workspace)

    assert artifacts["workspace"]["path"] == str(workspace)
    assert artifacts["overview"] == {"status": "ok"}
    assert artifacts["overview_file"] == {
        "path": str(output_dir / "overview.json"),
        "exists": True,
    }


def test_file_status_adds_modified_at_only_when_requested(tmp_path: Path) -> None:
    path = tmp_path / "artifact.txt"
    path.write_text("artifact", encoding="utf-8")

    assert file_status(path) == {"path": str(path), "exists": True}
    with_modified_at = file_status(path, include_modified_at=True)
    assert with_modified_at["path"] == str(path)
    assert with_modified_at["exists"] is True
    assert with_modified_at["modifiedAt"] is not None
