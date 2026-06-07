from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunAttempt, TaskRecord, TaskStatus
from backend.app.services.task_runtime_codex_state import (
    CODEX_PLAN_APPROVAL_NOTE,
    CODEX_PLAN_REGENERATION_NOTE,
    CODEX_START_NOTE,
    apply_codex_plan_approval_response,
    apply_codex_plan_regeneration_response,
    apply_codex_resume_response,
    apply_codex_start_response,
)


def _task(**overrides: object) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    payload = {
        "id": "task-codex-state",
        "team_id": "team-1",
        "created_by": "user-1",
        "name": "Codex State",
        "description": "State transition task.",
        "status": TaskStatus.paused_for_review,
        "codex_session_id": "old-session",
        "codex_thread_id": "old-thread",
        "codex_workspace_path": "old-workspace",
        "codex_status": "interrupted",
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return TaskRecord(**payload)


def test_apply_codex_start_response_sets_start_only_fields() -> None:
    started_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    task = _task(
        status=TaskStatus.failed,
        codex_started_at=None,
        codex_finished_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        last_run_attempt=RunAttempt(output_dir="old-attempt"),
    )

    updated = apply_codex_start_response(
        task,
        {
            "sessionId": "new-session",
            "threadId": "new-thread",
            "workspacePath": "new-workspace",
        },
        now=started_at,
    )

    assert updated.status == TaskStatus.running
    assert updated.executor_type == "codex"
    assert updated.codex_session_id == "new-session"
    assert updated.codex_thread_id == "new-thread"
    assert updated.codex_workspace_path == "new-workspace"
    assert updated.codex_status == "running"
    assert updated.codex_started_at == started_at
    assert updated.codex_finished_at is None
    assert updated.notes == CODEX_START_NOTE
    assert updated.last_run is None
    assert updated.last_run_attempt is None


def test_apply_codex_start_response_preserves_existing_started_at() -> None:
    original_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    task = _task(codex_started_at=original_started_at)

    updated = apply_codex_start_response(
        task,
        {"sessionId": "new-session"},
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert updated.codex_started_at == original_started_at
    assert updated.codex_thread_id == "old-thread"
    assert updated.codex_workspace_path == "old-workspace"


def test_apply_codex_resume_response_clears_quota_guard_and_finished_at() -> None:
    task = _task(
        codex_finished_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        structured_requirements={
            "quota_guard": {"status": "exhausted"},
            "codex": {"status": "interrupted"},
        },
        last_run_attempt=RunAttempt(output_dir="failed-attempt"),
    )

    updated = apply_codex_resume_response(
        task,
        {"sessionId": "resumed-session", "threadId": "resumed-thread"},
        notes="Codex 已从暂停位置继续执行。",
    )

    assert updated.status == TaskStatus.running
    assert updated.codex_session_id == "resumed-session"
    assert updated.codex_thread_id == "resumed-thread"
    assert updated.codex_finished_at is None
    assert updated.notes == "Codex 已从暂停位置继续执行。"
    assert updated.last_run_attempt is not None
    assert updated.structured_requirements == {"codex": {"status": "interrupted"}}


def test_apply_codex_plan_regeneration_response_clears_quota_guard() -> None:
    finished_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    task = _task(
        codex_finished_at=finished_at,
        structured_requirements={"quota_guard": {"status": "exhausted"}},
    )

    updated = apply_codex_plan_regeneration_response(task, {"threadId": "regen-thread"})

    assert updated.status == TaskStatus.running
    assert updated.codex_thread_id == "regen-thread"
    assert updated.codex_session_id == "old-session"
    assert updated.codex_finished_at == finished_at
    assert updated.notes == CODEX_PLAN_REGENERATION_NOTE
    assert updated.structured_requirements == {}


def test_apply_codex_plan_approval_response_preserves_existing_finished_at() -> None:
    finished_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    task = _task(codex_finished_at=finished_at)

    updated = apply_codex_plan_approval_response(
        task,
        {"sessionId": "approved-session", "threadId": "approved-thread"},
    )

    assert updated.status == TaskStatus.running
    assert updated.codex_session_id == "approved-session"
    assert updated.codex_thread_id == "approved-thread"
    assert updated.codex_finished_at == finished_at
    assert updated.notes == CODEX_PLAN_APPROVAL_NOTE
