from __future__ import annotations

import os
from pathlib import Path

from backend.app.models.task import WorkflowStage
from backend.app.services.task_run_artifacts import collect_stage_artifacts_by_stage, read_run_log_excerpt


def test_collect_stage_artifacts_by_stage_matches_known_artifact_names(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    code_dir = run_dir / "node_001" / "states"
    output_dir = run_dir / "node_001" / "output"
    code_dir.mkdir(parents=True)
    output_dir.mkdir()
    generated_code = code_dir / "generated_code.py"
    leaderboard = output_dir / "leaderboard.csv"
    ignored = output_dir / "unknown.bin"
    generated_code.write_text("print('ok')\n", encoding="utf-8")
    leaderboard.write_text("model,score\nridge,0.9\n", encoding="utf-8")
    ignored.write_bytes(b"ignored")

    collected = collect_stage_artifacts_by_stage(run_dir)

    assert collected[WorkflowStage.feature_engineering] == [str(generated_code)]
    assert collected[WorkflowStage.model_selection] == [str(leaderboard)]
    assert WorkflowStage.training_validation not in collected


def test_collect_stage_artifacts_by_stage_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert collect_stage_artifacts_by_stage(tmp_path / "missing") == {}
    assert collect_stage_artifacts_by_stage(None) == {}


def test_read_run_log_excerpt_prefers_report_and_truncates_tail(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = run_dir / "output"
    output_dir.mkdir(parents=True)
    (run_dir / "logs.txt").write_text("lower priority", encoding="utf-8")
    (output_dir / "report.md").write_text("abcdef", encoding="utf-8")

    assert read_run_log_excerpt(run_dir, max_chars=3) == "report.md\ndef"


def test_read_run_log_excerpt_uses_newest_log_when_primary_files_are_empty(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.txt").write_text("", encoding="utf-8")
    older = run_dir / "older.log"
    newer = run_dir / "newer.log"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    os.utime(older, (10, 10))
    os.utime(newer, (20, 20))

    assert read_run_log_excerpt(run_dir) == "newer.log\nnew"
    assert read_run_log_excerpt(run_dir / "missing") is None
