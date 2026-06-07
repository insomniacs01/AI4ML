from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
)
from backend.app.services.task_runtime_resume import (
    codex_interrupted,
    codex_waiting_improvement_review,
    codex_waiting_plan_approval,
    has_open_human_confirmation_requests,
    resume_note_for_improvement_decision,
)


def _task(*, codex_status: str | None) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-resume",
        team_id="team-1",
        created_by="user-1",
        name="Resume Task",
        description="Resume Codex task.",
        status=TaskStatus.paused_for_review,
        codex_status=codex_status,
        created_at=now,
        updated_at=now,
    )


def _human_request(status: HumanInteractionRequestStatus) -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id=f"request-{status.value}",
        team_id="team-1",
        task_id="task-resume",
        stage="data_analysis",
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_waiting_plan_approval_is_not_interrupted_resume() -> None:
    progress = {
        "status": "waiting_plan_approval",
        "current_step": "awaiting_plan_approval",
    }

    task = _task(codex_status="waiting_plan_approval")

    assert codex_waiting_plan_approval(task, progress) is True
    assert codex_interrupted(task, progress) is False


def test_interrupted_status_is_interrupted_resume() -> None:
    progress = {"status": "interrupted"}
    task = _task(codex_status="interrupted")

    assert codex_interrupted(task, progress) is True
    assert codex_waiting_plan_approval(task, progress) is False


def test_waiting_plan_approval_reads_progress_steps() -> None:
    progress = {
        "status": "running",
        "steps": [
            {"id": "dataset_analysis", "status": "completed"},
            {"id": "plan_ready", "status": "waiting_human"},
        ],
    }

    task = _task(codex_status=None)

    assert codex_waiting_plan_approval(task, progress) is True
    assert codex_interrupted(task, progress) is False


def test_waiting_improvement_review_reads_progress_steps() -> None:
    progress = {
        "status": "running",
        "steps": [
            {"id": "modeling", "status": "completed"},
            {"name": "waiting_improvement_approval", "status": "waiting_human"},
        ],
    }

    task = _task(codex_status=None)

    assert codex_waiting_improvement_review(task, progress) is True
    assert codex_waiting_plan_approval(task, progress) is False


def test_open_human_confirmation_requests_include_pending_and_open() -> None:
    pending = _human_request(HumanInteractionRequestStatus.pending)
    open_request = _human_request(HumanInteractionRequestStatus.open)
    confirmed = _human_request(HumanInteractionRequestStatus.confirmed)
    resolved = _human_request(HumanInteractionRequestStatus.resolved)

    assert has_open_human_confirmation_requests([pending]) is True
    assert has_open_human_confirmation_requests([open_request]) is True
    assert has_open_human_confirmation_requests([confirmed]) is False
    assert has_open_human_confirmation_requests([resolved]) is False


def test_resume_note_matches_improvement_decision() -> None:
    assert resume_note_for_improvement_decision("continue_improvement") == "Codex 已按用户选择继续执行改进方案。"
    assert resume_note_for_improvement_decision("stop_and_report") == "Codex 已按用户选择停止继续改进，正在生成当前结果报告。"
    assert resume_note_for_improvement_decision(None) == "Codex 已从暂停位置继续执行。"
