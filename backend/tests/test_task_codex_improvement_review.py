from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import RunAttempt, TaskRecord, TaskStatus
from backend.app.services.task_codex_improvement_review import (
    codex_improvement_plan_text,
    codex_stage_workspace_path,
    codex_workspace_improvement_plan_path,
    has_codex_improvement_review,
)


def _task(**overrides: object) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = {
        "id": "task-codex-improvement-review",
        "team_id": "team-1",
        "created_by": "user-1",
        "name": "Codex improvement review",
        "description": "Improvement review task.",
        "status": TaskStatus.paused_for_review,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return TaskRecord(**payload)


def test_codex_stage_workspace_path_prefers_current_workspace() -> None:
    task = _task(
        codex_workspace_path="current-workspace",
        last_run_attempt=RunAttempt(output_dir="attempt-workspace"),
    )

    assert codex_stage_workspace_path(task) == "current-workspace"


def test_codex_workspace_improvement_plan_path_reads_artifact_payload(tmp_path: Path) -> None:
    task = _task(codex_workspace_path=str(tmp_path / "workspace"))
    artifact_path = str(tmp_path / "artifact-plan.md")

    assert codex_workspace_improvement_plan_path(
        task,
        {"improvement_plan_file": {"exists": True, "path": artifact_path}},
    ) == artifact_path


def test_codex_workspace_improvement_plan_path_falls_back_to_workspace_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    plan_path = workspace / "output" / "improvement_plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("Improve metric.", encoding="utf-8")
    task = _task(codex_workspace_path=str(workspace))

    assert codex_workspace_improvement_plan_path(task, {}) == str(plan_path)
    assert codex_improvement_plan_text(task, {}) == "Improve metric."


def test_codex_improvement_plan_text_prefers_artifact_text(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    plan_path = workspace / "output" / "improvement_plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("Workspace text.", encoding="utf-8")
    task = _task(codex_workspace_path=str(workspace))

    assert codex_improvement_plan_text(task, {"improvement_plan": "Artifact text."}) == "Artifact text."


def test_has_codex_improvement_review_detects_status_text_and_file_payload() -> None:
    assert has_codex_improvement_review({"progress": {"status": "waiting_improvement_review"}}) is True
    assert has_codex_improvement_review({"progress": {"current_step": "improvement_review"}}) is True
    assert has_codex_improvement_review({"improvement_plan": "  improve model  "}) is True
    assert has_codex_improvement_review({"improvement_plan_file": {"exists": True}}) is True
    assert has_codex_improvement_review({"progress": {"status": "running"}}) is False
    assert has_codex_improvement_review(None) is False


def test_has_codex_improvement_review_ignores_stop_and_report_result() -> None:
    assert has_codex_improvement_review(
        {
            "progress": {"status": "partial", "current_step": "stop_and_report_completed"},
            "improvement_plan": "Historical improvement options.",
            "improvement_plan_file": {"exists": True},
            "report": {"exists": True},
            "predict": {"exists": True},
            "metrics": {"acceptance": {"passed": False}},
        }
    ) is False
