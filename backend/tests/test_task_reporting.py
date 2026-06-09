from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models.task import RunSummary, TaskRecord
from backend.app.services.task_report_codex_summary import codex_result_summary
from backend.app.services import task_reporting


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-reporting",
        team_id="team-1",
        created_by="user-1",
        name="Reporting Task",
        description="Build report summary.",
        created_at=now,
        updated_at=now,
    )


def test_codex_result_summary_uses_selected_model_metric_and_rationale() -> None:
    metrics = {
        "selected_model": {
            "name": "LightGBM",
            "cross_validation": {"macro_f1_mean": "0.81234", "accuracy": 0.9},
            "selection_rationale": " Best validation tradeoff. ",
        }
    }

    assert codex_result_summary(_task(), metrics) == [
        "最佳模型：LightGBM",
        "评价指标：macro_f1_mean = 0.81234",
        "Best validation tradeoff.",
    ]


def test_codex_result_summary_prefers_task_last_run_metric_and_model_fallback() -> None:
    task = _task()
    task.last_run = RunSummary(
        best_model="RandomForest",
        metric_name="mae",
        metric_value=2.34567,
        output_dir="workspace",
    )

    assert codex_result_summary(task, {"selected_model": {"holdout": {"rmse": 9.9}}}) == [
        "最佳模型：RandomForest",
        "评价指标：mae = 2.34567",
    ]


def test_codex_result_summary_uses_final_model_flat_validation_metric() -> None:
    metrics = {
        "final_model": {"name": "LogisticRegression", "validation_accuracy": 0.9333333333},
        "candidate_models": {"LogisticRegression": {"validation_accuracy": 0.9333333333}},
    }

    assert codex_result_summary(_task(), metrics) == [
        "最佳模型：LogisticRegression",
        "评价指标：accuracy = 0.933333",
    ]


def test_codex_report_can_skip_dataset_file_profile_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "report.md").write_text("# Report", encoding="utf-8")
    (output_dir / "metrics.json").write_text('{"selected_model":{"name":"LightGBM"}}', encoding="utf-8")
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    task = _task()
    task.codex_workspace_path = str(workspace)
    task.dataset_path = str(dataset_path)

    def fail_if_file_profile_is_built(*args: object, **kwargs: object) -> None:
        raise AssertionError("fast Codex report path must not scan dataset files")

    monkeypatch.setattr(task_reporting, "build_dataset_profile", fail_if_file_profile_is_built)

    report = task_reporting.build_codex_task_model_report(task, resolve_dataset_from_file=False)

    assert report is not None
    assert report.report_markdown == "# Report"
    assert report.dataset_profile is None


def test_codex_report_reads_feature_importance_file_when_metrics_lacks_importance(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "report.md").write_text("# Report", encoding="utf-8")
    (output_dir / "metrics.json").write_text(
        '{"final_model":{"name":"LogisticRegression","validation_accuracy":0.93}}',
        encoding="utf-8",
    )
    (output_dir / "feature_importance.json").write_text(
        '[{"feature":"income","importance":0.8}]',
        encoding="utf-8",
    )
    task = _task()
    task.codex_workspace_path = str(workspace)

    report = task_reporting.build_codex_task_model_report(task, resolve_dataset_from_file=False)

    assert report is not None
    assert [(item.feature, item.importance) for item in report.feature_importance] == [("income", 0.8)]


def test_codex_report_fast_path_does_not_scan_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _task()
    task.codex_workspace_path = str(tmp_path / "missing-workspace")
    task.codex_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def fail_if_full_workspace_resolution_runs(*args: object, **kwargs: object) -> None:
        raise AssertionError("fast report path must not scan the workspace root")

    monkeypatch.setattr(task_reporting, "resolve_codex_workspace", fail_if_full_workspace_resolution_runs)
    monkeypatch.setattr(
        task_reporting,
        "get_settings",
        lambda: type("Settings", (), {"codex_workspace_root": tmp_path / "workspaces"})(),
    )

    report = task_reporting.build_codex_task_model_report(task, resolve_workspace_by_scan=False)

    assert report is None
