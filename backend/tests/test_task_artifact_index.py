from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.app.models.task import RunAttempt, TaskRecord
from backend.app.services.task_artifact_index import build_run_artifact_index, find_feature_importance_paths
from backend.app.services.task_artifacts import build_run_artifact_index as build_compat_run_artifact_index


def test_run_artifact_index_uses_latest_candidates_and_node_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs" / "task-1" / "attempt-1"
    node_dir = output_dir / "node_1"
    (node_dir / "output").mkdir(parents=True)
    (node_dir / "states").mkdir()
    (output_dir / "output").mkdir()

    root_metrics = output_dir / "output" / "metrics.json"
    node_summary = node_dir / "output" / "run_summary.json"
    root_metrics.write_text("{}", encoding="utf-8")
    node_summary.write_text("{}", encoding="utf-8")
    _set_mtime(root_metrics, 10)
    _set_mtime(node_summary, 20)

    token_usage = node_dir / "output" / "token_usage.json"
    generated_code = node_dir / "states" / "python_code.py"
    feature_importance = node_dir / "output" / "feature_importance.csv"
    token_usage.write_text("{}", encoding="utf-8")
    generated_code.write_text("print('ok')\n", encoding="utf-8")
    feature_importance.write_text("feature,importance\nx,1\n", encoding="utf-8")

    index = build_run_artifact_index(
        _task(output_dir),
        settings=SimpleNamespace(run_output_dir=tmp_path / "runs"),
    )

    assert index.requested_output_dir == output_dir
    assert index.output_dir == output_dir
    assert index.run_summary_path == node_summary
    assert index.token_usage_path == token_usage
    assert index.generated_code_path == generated_code
    assert index.feature_importance_paths == [feature_importance]
    assert index.has_run_summary is True
    assert index.has_token_usage is True
    assert index.has_generated_code is True


def test_find_feature_importance_paths_checks_root_best_run_and_nodes(tmp_path: Path) -> None:
    root_feature = tmp_path / "feature_importance.json"
    best_run_feature = tmp_path / "best_run" / "output" / "feature_importances.csv"
    node_feature = tmp_path / "node_1" / "output" / "feature_importance.csv"
    best_run_feature.parent.mkdir(parents=True)
    node_feature.parent.mkdir(parents=True)
    root_feature.write_text("{}", encoding="utf-8")
    best_run_feature.write_text("feature,importance\n", encoding="utf-8")
    node_feature.write_text("feature,importance\n", encoding="utf-8")

    paths = find_feature_importance_paths(tmp_path, node_dirs=[tmp_path / "node_1"])

    assert set(paths) == {root_feature, best_run_feature, node_feature}


def test_task_artifacts_compat_wrapper_uses_patched_settings(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "runs" / "task-1" / "attempt-1"
    output_dir.mkdir(parents=True)
    (output_dir / "run_summary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "backend.app.services.task_artifacts.get_settings",
        lambda: SimpleNamespace(run_output_dir=tmp_path / "runs"),
    )

    index = build_compat_run_artifact_index(_task(output_dir))

    assert index.output_dir == output_dir
    assert index.run_summary_path == output_dir / "run_summary.json"


def _task(output_dir: Path) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Task",
        description="Train a model.",
        last_run_attempt=RunAttempt(output_dir=str(output_dir)),
        created_at=now,
        updated_at=now,
    )


def _set_mtime(path: Path, timestamp: int) -> None:
    os.utime(path, (timestamp, timestamp))
