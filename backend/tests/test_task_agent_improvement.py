from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunSummary, TaskRecord
from backend.app.services.task_agent_improvement import build_next_improvement


def _task(*, leaderboard: list[dict] | None = None) -> TaskRecord:
    now = datetime.now(timezone.utc)
    task = TaskRecord(
        id="task-improvement",
        team_id="team-1",
        created_by="user-1",
        name="Improvement Task",
        description="Decide next improvement.",
        created_at=now,
        updated_at=now,
    )
    if leaderboard is not None:
        task.last_run = RunSummary(
            best_model="ridge",
            metric_name="mae",
            metric_value=2.0,
            leaderboard=leaderboard,
            output_dir="D:/runs/task",
        )
    return task


def test_next_improvement_prioritizes_blocking_gates() -> None:
    suggestion = build_next_improvement(
        _task(),
        [{"id": "semantic_ready", "status": "blocked", "detail": "缺少目标列。"}],
    )

    assert suggestion["status"] == "needs_human_or_retry"
    assert suggestion["reason_code"] == "semantic_ready"
    assert suggestion["detail"] == "缺少目标列。"
    assert suggestion["changed_config"] == {"rerun_from_stage": "data_analysis"}


def test_next_improvement_proposes_training_retry_for_model_baseline_warning() -> None:
    suggestion = build_next_improvement(
        _task(leaderboard=[{"model": "ridge"}, {"model": "tree"}]),
        [{"id": "model_vs_baseline", "status": "warning", "detail": "not better"}],
    )

    assert suggestion["status"] == "proposed"
    assert suggestion["reason_code"] == "model_vs_baseline"
    assert suggestion["changed_config"]["rerun_from_stage"] == "training_validation"
    assert suggestion["changed_config"]["increase_candidate_models"] is True


def test_next_improvement_proposes_data_review_for_leakage_warning() -> None:
    suggestion = build_next_improvement(
        _task(leaderboard=[{"model": "ridge"}, {"model": "tree"}]),
        [{"id": "leakage_review", "status": "warning", "detail": "score too high"}],
    )

    assert suggestion["status"] == "proposed"
    assert suggestion["reason_code"] == "leakage_review"
    assert suggestion["detail"] == "score too high"
    assert suggestion["changed_config"] == {"rerun_from_stage": "data_analysis", "review_leakage_columns": True}


def test_next_improvement_proposes_more_candidates_for_single_model_run() -> None:
    suggestion = build_next_improvement(_task(leaderboard=[{"model": "ridge"}]), [])

    assert suggestion["status"] == "proposed"
    assert suggestion["reason_code"] == "candidate_models"
    assert suggestion["changed_config"] == {"rerun_from_stage": "training_validation", "min_candidate_models": 3}


def test_next_improvement_defaults_to_pending_or_not_needed() -> None:
    assert build_next_improvement(_task(), [])["status"] == "pending"
    assert build_next_improvement(_task(leaderboard=[{"model": "ridge"}, {"model": "tree"}]), [])["status"] == "not_needed"
