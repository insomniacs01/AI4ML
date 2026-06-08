from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import (
    DatasetColumnProfile,
    DatasetProfile,
    HumanInteractionDecisionAction,
    HumanInteractionRequestStatus,
    RunAttempt,
    RunSummary,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_human_parameter_values import HUMAN_PARAMETERS_KEY, PARAMETER_HISTORY_KEY
from backend.app.services.task_human_columns import column_names
from backend.app.services.task_human_parameters import apply_human_decision_parameters


def _task(*, dataset_path: str | None = None, profile: DatasetProfile | None = None) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-human-parameters",
        team_id="team-1",
        created_by="user-1",
        name="Human Parameters Task",
        description="Resolve human parameter columns.",
        dataset_path=dataset_path,
        dataset_profile=profile,
        created_at=now,
        updated_at=now,
    )


def _profile(names: list[str]) -> DatasetProfile:
    return DatasetProfile(
        filename="train.csv",
        path="D:/datasets/train.csv",
        row_count=10,
        column_count=len(names),
        columns=[
            DatasetColumnProfile(
                name=name,
                inferred_type="text",
                non_empty_count=10,
                missing_count=0,
                missing_ratio=0.0,
            )
            for name in names
        ],
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _request(stage: WorkflowStage) -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id="request-1",
        team_id="team-1",
        task_id="task-human-parameters",
        stage=stage,
        status=HumanInteractionRequestStatus.open,
        requested_by="user-1",
        created_at=now,
        updated_at=now,
    )


def _decision(details: dict) -> TaskHumanRequestDecisionRequest:
    return TaskHumanRequestDecisionRequest(
        action=HumanInteractionDecisionAction.approve,
        decision_summary="Approved parameter update.",
        details=details,
    )


def test_apply_training_parameters_invalidates_existing_run_for_rerun() -> None:
    task = _task()
    task.status = TaskStatus.completed
    task.dataset_filename = "train.csv"
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir="successful-run",
    )
    task.last_run_attempt = RunAttempt(output_dir="failed-run")

    updated = apply_human_decision_parameters(
        task,
        _request(WorkflowStage.training_validation),
        _decision({"parameters": {"time_limit": "120", "cv_folds": 5, "metric_name": "MAE"}}),
        decided_by="reviewer-1",
    )

    assert updated is True
    assert task.status == TaskStatus.uploaded
    assert task.last_run is None
    assert task.last_run_attempt is None
    requirements = task.structured_requirements
    assert requirements["metric_name"] == "mae"
    assert requirements["training_constraints"] == {"time_limit": 120, "cv_folds": 5, "metric_name": "mae"}
    assert requirements[HUMAN_PARAMETERS_KEY][WorkflowStage.training_validation.value]["request_id"] == "request-1"
    assert requirements[HUMAN_PARAMETERS_KEY][WorkflowStage.training_validation.value]["updated_by"] == "reviewer-1"
    assert requirements[PARAMETER_HISTORY_KEY][-1]["parameters"] == {"time_limit": 120, "cv_folds": 5, "metric_name": "mae"}
    assert requirements["human_loop"]["rerun_requested"] is True
    assert requirements["human_loop"]["rerun_from_stage"] == WorkflowStage.training_validation.value
    assert requirements["human_loop"]["rerun_reason"] == "Human-selected node parameters changed the modeling configuration."
    assert task.notes == "Human parameters updated for training_validation."


def test_column_names_prefers_task_dataset_profile() -> None:
    names = column_names(
        _task(profile=_profile(["profile_a", "profile_target"])),
        {"column_names": ["requirement_a", "requirement_target"]},
    )

    assert names == ["profile_a", "profile_target"]


def test_column_names_reads_serialized_profile_columns_with_existing_coercion() -> None:
    names = column_names(
        _task(),
        {
            "dataset_profile": {
                "columns": [
                    {"name": " age "},
                    {"name": ""},
                    {"name": None},
                    "invalid",
                ]
            }
        },
    )

    assert names == ["age", "None"]


def test_column_names_falls_back_to_csv_header(tmp_path: Path) -> None:
    dataset_path = tmp_path / "train.csv"
    dataset_path.write_text("age,income,target\n18,2000,yes\n", encoding="utf-8")

    names = column_names(_task(dataset_path=str(dataset_path)), {})

    assert names == ["age", "income", "target"]
