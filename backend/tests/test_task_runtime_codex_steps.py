from __future__ import annotations

from types import SimpleNamespace

from backend.app.models.task import TaskStatus, WorkflowStageStatus
from backend.app.services.task_runtime_codex_steps import codex_steps_from_progress


def test_codex_steps_from_progress_reads_raw_steps_fallback() -> None:
    progress = SimpleNamespace(
        status="running",
        raw_steps=[
            {
                "status": "done",
                "summary": "generated artifacts",
                "artifacts": ["output/report.md"],
            }
        ],
    )

    steps = codex_steps_from_progress(progress)

    assert len(steps) == 1
    assert steps[0].id == "codex_step_1"
    assert steps[0].status == WorkflowStageStatus.completed.value
    assert steps[0].summary == "generated artifacts"
    assert steps[0].artifacts == ["output/report.md"]


def test_codex_steps_from_progress_maps_interrupted_pause_to_waiting_human() -> None:
    progress = SimpleNamespace(
        status="running",
        task_status=TaskStatus.paused_for_review,
        codex_raw_steps=[{"id": "approval", "status": "interrupted"}],
    )

    steps = codex_steps_from_progress(progress)

    assert steps[0].status == WorkflowStageStatus.waiting_human.value
