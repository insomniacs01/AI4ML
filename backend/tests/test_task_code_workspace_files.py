from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.task_code_versions import VERSION_MANIFEST_NAME
from backend.app.services.task_code_workspace_files import (
    artifact_entry_from_path,
    collect_workspace_entries,
    resolve_artifact_path,
)


def test_collect_workspace_entries_includes_supported_text_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    code_dir = run_dir / "output" / "code"
    code_dir.mkdir(parents=True)
    (code_dir / "final_modeling.py").write_text("print('ok')\n", encoding="utf-8")
    (run_dir / VERSION_MANIFEST_NAME).write_text("[]", encoding="utf-8")
    (run_dir / "image.png").write_bytes(b"\x89PNG\r\n")

    entries = collect_workspace_entries(run_dir)

    assert [entry.path for entry in entries] == ["output/code/final_modeling.py"]
    assert entries[0].editable is True


def test_resolve_artifact_path_rejects_escape_and_best_run_shadow_copy(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    best_run = run_dir / "best_run" / "generated_code.py"
    best_run.parent.mkdir()
    best_run.write_text("print('shadow')\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="escapes"):
        resolve_artifact_path(run_dir, "../outside.py")
    with pytest.raises(PermissionError, match="best_run"):
        resolve_artifact_path(run_dir, "best_run/generated_code.py")


def test_artifact_entry_from_path_adds_node_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    node_dir = run_dir / "node_003" / "states"
    node_dir.mkdir(parents=True)
    artifact = node_dir / "python_coder_prompt.txt"
    artifact.write_text("prompt", encoding="utf-8")

    entry = artifact_entry_from_path(run_dir, artifact)

    assert entry is not None
    assert entry.node == "node_003"
    assert entry.path == "node_003/states/python_coder_prompt.txt"
