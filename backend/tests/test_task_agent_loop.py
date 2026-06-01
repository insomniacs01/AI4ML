from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.app.models.task import DatasetColumnProfile, DatasetProfile, RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_agent_loop import (
    initialize_agent_loop_for_upload,
    refresh_agent_loop_after_analysis,
    refresh_agent_loop_after_run,
    refresh_agent_loop_after_run_failure,
)


def _task(
    *,
    dataset_path: str | None = None,
    label_column: str | None = None,
    problem_type: str | None = None,
    metric_name: str | None = None,
) -> TaskRecord:
    now = datetime.now(timezone.utc)
    requirements = {"metric_name": metric_name} if metric_name else None
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Task",
        description="Train a tabular model.",
        label_column=label_column,
        problem_type=problem_type,
        status=TaskStatus.uploaded,
        dataset_filename="train.csv" if dataset_path else None,
        dataset_path=dataset_path,
        structured_requirements=requirements,
        created_at=now,
        updated_at=now,
    )


def _agent_loop(task: TaskRecord) -> dict:
    assert isinstance(task.structured_requirements, dict)
    loop = task.structured_requirements.get("agent_loop")
    assert isinstance(loop, dict)
    return loop


def test_upload_initializes_pending_agent_loop() -> None:
    task = initialize_agent_loop_for_upload(_task(dataset_path="D:/tmp/train.csv"))

    loop = _agent_loop(task)

    assert loop["task_id"] == "task-1"
    assert loop["baseline"]["status"] == "pending"
    assert loop["tuning_attempts"] == []
    assert loop["quality_gates"][0]["id"] == "semantic_ready"
    assert loop["quality_gates"][0]["status"] == "blocked"
    assert loop["workflow"][3]["key"] == "baseline"
    assert loop["workflow"][3]["status"] == "pending"


def test_checklist_includes_profile_risk_items() -> None:
    task = _task(
        dataset_path="D:/tmp/train.csv",
        label_column="target",
        problem_type="classification",
        metric_name="accuracy",
    )
    task.dataset_profile = DatasetProfile(
        filename="train.csv",
        path=task.dataset_path,
        row_count=20,
        column_count=2,
        columns=[
            DatasetColumnProfile(
                name="feature",
                inferred_type="number",
                non_empty_count=10,
                missing_count=10,
                missing_ratio=0.5,
            ),
            DatasetColumnProfile(
                name="target",
                inferred_type="text",
                non_empty_count=20,
                missing_count=0,
                missing_ratio=0.0,
            ),
        ],
        generated_at=datetime.now(timezone.utc),
    )

    initialize_agent_loop_for_upload(task)

    checklist = _agent_loop(task)["checklist"]
    by_id = {item["id"]: item for item in checklist}
    assert by_id["target_in_columns"]["status"] == "passed"
    assert by_id["missing_values"]["status"] == "warning"
    assert "feature(50%)" in by_id["missing_values"]["detail"]
    assert by_id["sample_size"]["status"] == "warning"


def test_analysis_computes_regression_mean_baseline(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "feature,target\n"
        "a,1\n"
        "b,2\n"
        "c,3\n"
        "d,4\n"
        "e,5\n"
        "f,6\n"
        "g,7\n"
        "h,8\n"
        "i,9\n"
        "j,10\n",
        encoding="utf-8",
    )
    task = _task(
        dataset_path=str(dataset),
        label_column="target",
        problem_type="regression",
        metric_name="mae",
    )

    refresh_agent_loop_after_analysis(task)

    loop = _agent_loop(task)
    baseline = loop["baseline"]
    assert baseline["status"] == "completed"
    assert baseline["method"] == "mean_target_baseline"
    assert baseline["metric_name"] == "mae"
    assert baseline["metric_value"] == 2.5
    assert baseline["validation_score"] == -2.5
    assert baseline["train_count"] == 8
    assert baseline["validation_count"] == 2
    assert loop["tuning_attempts"][0]["correlation_key"] == "baseline"
    assert loop["tuning_attempts"][0]["metric_after"]["metric_value"] == 2.5


def test_analysis_computes_classification_majority_baseline(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "feature,target\n"
        "a,yes\n"
        "b,no\n"
        "c,yes\n"
        "d,yes\n"
        "e,no\n"
        "f,yes\n"
        "g,yes\n"
        "h,no\n"
        "i,yes\n"
        "j,yes\n",
        encoding="utf-8",
    )
    task = _task(
        dataset_path=str(dataset),
        label_column="target",
        problem_type="classification",
        metric_name="accuracy",
    )

    refresh_agent_loop_after_analysis(task)

    baseline = _agent_loop(task)["baseline"]
    assert baseline["status"] == "completed"
    assert baseline["method"] == "majority_class_baseline"
    assert baseline["metric_name"] == "accuracy"
    assert baseline["metric_value"] == 1.0
    assert math.isclose(baseline["majority_ratio"], 5 / 8)
    assert baseline["class_distribution"] == {"yes": 5, "no": 3}


def test_run_refresh_records_model_attempt_and_improvement_proposal(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "feature,target\n"
        "a,1\n"
        "b,2\n"
        "c,3\n"
        "d,4\n"
        "e,5\n"
        "f,6\n"
        "g,7\n"
        "h,8\n"
        "i,9\n"
        "j,10\n",
        encoding="utf-8",
    )
    task = _task(
        dataset_path=str(dataset),
        label_column="target",
        problem_type="regression",
        metric_name="mae",
    )
    refresh_agent_loop_after_analysis(task)
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=3.0,
        validation_score=-3.0,
        leaderboard=[{"model": "ridge"}],
        output_dir=str(tmp_path / "output"),
    )

    refresh_agent_loop_after_run(task)

    loop = _agent_loop(task)
    attempts = loop["tuning_attempts"]
    model_attempt = next(item for item in attempts if item["kind"] == "model_run")
    proposal = next(item for item in attempts if item["kind"] == "improvement_proposal")
    model_gate = next(item for item in loop["quality_gates"] if item["id"] == "model_vs_baseline")
    assert model_attempt["accepted"] is False
    assert model_attempt["status"] == "needs_improvement"
    assert proposal["correlation_key"].endswith(":model_vs_baseline")
    assert loop["next_improvement"]["reason_code"] == "model_vs_baseline"
    assert model_gate["status"] == "warning"


def test_run_refresh_flags_leakage_review_for_suspicious_classification_score(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "feature,target\n"
        "a,no\n"
        "b,yes\n"
        "c,yes\n"
        "d,yes\n"
        "e,yes\n"
        "f,no\n"
        "g,yes\n"
        "h,no\n"
        "i,no\n"
        "j,yes\n",
        encoding="utf-8",
    )
    task = _task(
        dataset_path=str(dataset),
        label_column="target",
        problem_type="classification",
        metric_name="accuracy",
    )
    refresh_agent_loop_after_analysis(task)
    task.last_run = RunSummary(
        best_model="tabular_net",
        metric_name="accuracy",
        metric_value=0.999,
        validation_score=0.999,
        leaderboard=[{"model": "tabular_net"}, {"model": "tree"}],
        output_dir=str(tmp_path / "output"),
    )

    refresh_agent_loop_after_run(task)

    loop = _agent_loop(task)
    leakage_gate = next(item for item in loop["quality_gates"] if item["id"] == "leakage_review")
    assert leakage_gate["status"] == "warning"
    assert loop["next_improvement"]["reason_code"] == "leakage_review"


def test_run_failure_records_deduplicated_attempt_and_blocking_gate(tmp_path) -> None:
    dataset = tmp_path / "train.csv"
    dataset.write_text(
        "feature,target\n"
        "a,1\n"
        "b,2\n"
        "c,3\n"
        "d,4\n"
        "e,5\n"
        "f,6\n"
        "g,7\n"
        "h,8\n"
        "i,9\n"
        "j,10\n",
        encoding="utf-8",
    )
    task = _task(
        dataset_path=str(dataset),
        label_column="target",
        problem_type="regression",
        metric_name="mae",
    )
    refresh_agent_loop_after_analysis(task)
    task.status = TaskStatus.failed

    refresh_agent_loop_after_run_failure(task, error_summary="training crashed", output_dir="run-1")
    refresh_agent_loop_after_run_failure(task, error_summary="training crashed", output_dir="run-1")

    loop = _agent_loop(task)
    failures = [item for item in loop["tuning_attempts"] if item["kind"] == "run_failure"]
    failure_gate = next(item for item in loop["quality_gates"] if item["id"] == "run_failure")
    assert len(failures) == 1
    assert failures[0]["correlation_key"] == "run_failure:run-1"
    assert failures[0]["status"] == "failed"
    assert failure_gate["status"] == "blocked"
    assert loop["next_improvement"]["reason_code"] == "run_failure"
