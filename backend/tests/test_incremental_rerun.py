from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from backend.app.core.config import Settings
from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus, WorkflowStage
from backend.app.services.task_incremental_rerun import (
    IncrementalRerunPreconditionError,
    run_task_incrementally,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _settings(tmpdir: Path) -> Settings:
    return Settings(
        run_output_dir=tmpdir / "runs",
        storage_dir=tmpdir / "storage",
        mlzero_execution_mode="python",
        mlzero_python_executable=Path(sys.executable),
    )


def _task(*, source_output_dir: Path, last_run: RunSummary | None = None) -> TaskRecord:
    now = _utcnow()
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Incremental Task",
        description="Train from a CSV.",
        label_column="label",
        problem_type="classification",
        status=TaskStatus.completed,
        dataset_filename="train.csv",
        dataset_path=str(source_output_dir / "input" / "train.csv"),
        last_run=last_run,
        last_run_attempt=None if last_run else RunAttempt(output_dir=str(source_output_dir)),
        created_at=now,
        updated_at=now,
    )


def _write_dataset(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("feature,label\n1,A\n2,B\n3,A\n", encoding="utf-8")


def _write_reusable_generated_code(source_output_dir: Path, *, node_name: str = "node_7") -> Path:
    node_dir = source_output_dir / node_name
    node_dir.mkdir(parents=True, exist_ok=True)
    code = f"""
import csv
import json
import os

input_dir = r"{source_output_dir / 'input'}"
output_dir = r"{node_dir / 'output'}"

os.makedirs(output_dir, exist_ok=True)
with open(os.path.join(input_dir, "train.csv"), newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
if not rows:
    raise RuntimeError("empty training data")

leaderboard = [
    {{"model": "CandidateA", "validation_score": 0.8}},
    {{"model": "CandidateB", "validation_score": 0.7}},
]
with open(os.path.join(output_dir, "leaderboard.json"), "w", encoding="utf-8") as handle:
    json.dump(leaderboard, handle)
with open(os.path.join(output_dir, "run_summary.json"), "w", encoding="utf-8") as handle:
    json.dump({{
        "best_model": "CandidateA",
        "metric_name": "accuracy",
        "metric_value": 0.8,
        "validation_score": 0.8,
        "tool": "unit-test",
        "candidate_model_count": 2
    }}, handle)
"""
    code_path = node_dir / "generated_code.py"
    code_path.write_text(code, encoding="utf-8")
    return code_path


def _write_source_summary(source_output_dir: Path) -> RunSummary:
    source_output_dir.mkdir(parents=True, exist_ok=True)
    leaderboard = [
        {"model": "CandidateA", "validation_score": 0.8},
        {"model": "CandidateB", "validation_score": 0.7},
    ]
    (source_output_dir / "leaderboard.json").write_text(json.dumps(leaderboard), encoding="utf-8")
    (source_output_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "best_model": "CandidateA",
                "metric_name": "accuracy",
                "metric_value": 0.8,
                "validation_score": 0.8,
                "tool": "unit-test",
                "candidate_model_count": 2,
            }
        ),
        encoding="utf-8",
    )
    return RunSummary(
        best_model="CandidateA",
        metric_name="accuracy",
        metric_value=0.8,
        leaderboard=leaderboard,
        output_dir=str(source_output_dir),
    )


class IncrementalRerunTests(TestCase):
    def test_training_incremental_rerun_reuses_generated_code_with_new_paths(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            tmpdir = Path(raw_tmp)
            source_output_dir = tmpdir / "source-run"
            dataset_path = source_output_dir / "input" / "train.csv"
            _write_dataset(dataset_path)
            _write_reusable_generated_code(source_output_dir)

            result = run_task_incrementally(
                _task(source_output_dir=source_output_dir),
                dataset_path,
                settings=_settings(tmpdir),
                start_stage=WorkflowStage.training_validation,
                time_limit=5,
            )

            self.assertEqual(result.summary.best_model, "CandidateA")
            self.assertNotEqual(Path(result.summary.output_dir), source_output_dir)
            self.assertTrue((Path(result.summary.output_dir) / "run_summary.json").exists())
            self.assertTrue((Path(result.summary.output_dir) / "incremental_rerun_manifest.json").exists())
            self.assertFalse((source_output_dir / "node_7" / "output" / "run_summary.json").exists())

    def test_incremental_rerun_requires_generated_code_for_training_stage(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            tmpdir = Path(raw_tmp)
            source_output_dir = tmpdir / "source-run"
            dataset_path = source_output_dir / "input" / "train.csv"
            _write_dataset(dataset_path)

            with self.assertRaises(IncrementalRerunPreconditionError):
                run_task_incrementally(
                    _task(source_output_dir=source_output_dir),
                    dataset_path,
                    settings=_settings(tmpdir),
                    start_stage=WorkflowStage.training_validation,
                    time_limit=5,
                )

    def test_report_incremental_rerun_rebuilds_report_without_execution(self) -> None:
        with TemporaryDirectory() as raw_tmp:
            tmpdir = Path(raw_tmp)
            source_output_dir = tmpdir / "source-run"
            dataset_path = source_output_dir / "input" / "train.csv"
            _write_dataset(dataset_path)
            source_summary = _write_source_summary(source_output_dir)

            result = run_task_incrementally(
                _task(source_output_dir=source_output_dir, last_run=source_summary),
                dataset_path,
                settings=_settings(tmpdir),
                start_stage=WorkflowStage.report_generation,
                time_limit=5,
            )

            output_dir = Path(result.summary.output_dir)
            self.assertEqual(result.summary.metric_value, 0.8)
            self.assertTrue((output_dir / "report_snapshot.md").exists())
            self.assertTrue((output_dir / "incremental_rerun_manifest.json").exists())
            manifest = json.loads((output_dir / "incremental_rerun_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["mode"], "incremental_report_rebuild")
