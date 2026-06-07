from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
)
from backend.app.services.task_codex_human_gates import (
    CODEX_IMPROVEMENT_REVIEW_VERSION_ID,
    CODEX_PLAN_APPROVAL_VERSION_ID,
    codex_improvement_review_version_id,
    has_confirmed_codex_plan_request,
    has_existing_codex_improvement_review_request,
    has_open_codex_plan_request,
)


def _task(*, human_loop: dict | None = None) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    structured_requirements = {"human_loop": human_loop} if human_loop is not None else None
    return TaskRecord(
        id="task-codex-gates",
        team_id="team-1",
        created_by="user-1",
        name="Codex gates",
        description="Check Codex human gates.",
        status=TaskStatus.waiting_human,
        structured_requirements=structured_requirements,
        created_at=now,
        updated_at=now,
    )


def _request(
    *,
    status: HumanInteractionRequestStatus,
    version_id: str | None = None,
    payload: dict | None = None,
    decision: dict | None = None,
) -> TaskHumanRequestRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskHumanRequestRecord(
        id=f"request-{status.value}",
        team_id="team-1",
        task_id="task-codex-gates",
        stage="data_analysis",
        status=status,
        version_id=version_id,
        payload=payload,
        decision=decision,
        created_at=now,
        updated_at=now,
    )


def test_has_open_codex_plan_request_detects_active_plan_request() -> None:
    requests = [
        _request(status=HumanInteractionRequestStatus.confirmed, version_id=CODEX_PLAN_APPROVAL_VERSION_ID),
        _request(status=HumanInteractionRequestStatus.open, version_id=CODEX_PLAN_APPROVAL_VERSION_ID),
    ]

    assert has_open_codex_plan_request(requests) is True


def test_has_confirmed_codex_plan_request_reads_human_loop_decisions() -> None:
    task = _task(
        human_loop={
            "latest_decision": {
                "request_type": "codex_plan_approval",
                "action": "approve",
                "resume_task": True,
            }
        }
    )

    assert has_confirmed_codex_plan_request(task, []) is True


def test_has_confirmed_codex_plan_request_ignores_non_resume_decision() -> None:
    task = _task(
        human_loop={
            "latest_decision": {
                "request_type": "codex_plan_approval",
                "action": "approve",
                "resume_task": False,
            }
        }
    )

    assert has_confirmed_codex_plan_request(task, []) is False


def test_has_confirmed_codex_plan_request_reads_request_decision() -> None:
    request = _request(
        status=HumanInteractionRequestStatus.skipped,
        version_id=CODEX_PLAN_APPROVAL_VERSION_ID,
        decision={"action": "skip"},
    )

    assert has_confirmed_codex_plan_request(_task(), [request]) is True


def test_existing_improvement_review_detects_active_request() -> None:
    request = _request(
        status=HumanInteractionRequestStatus.open,
        version_id="other-version",
        payload={"request_type": "codex_improvement_review"},
    )

    assert has_existing_codex_improvement_review_request([request], version_id="target-version") is True


def test_existing_improvement_review_detects_completed_same_version() -> None:
    request = _request(
        status=HumanInteractionRequestStatus.resolved,
        version_id="target-version",
        payload={"request_type": "codex_improvement_review"},
    )

    assert has_existing_codex_improvement_review_request([request], version_id="target-version") is True


def test_existing_improvement_review_ignores_completed_different_version() -> None:
    request = _request(
        status=HumanInteractionRequestStatus.resolved,
        version_id="other-version",
        payload={"request_type": "codex_improvement_review"},
    )

    assert has_existing_codex_improvement_review_request([request], version_id="target-version") is False


def test_codex_improvement_review_version_id_uses_file_mtime(tmp_path: Path) -> None:
    path = tmp_path / "improvement_plan.md"
    path.write_text("plan", encoding="utf-8")

    assert codex_improvement_review_version_id(str(path)) == (
        f"{CODEX_IMPROVEMENT_REVIEW_VERSION_ID}:{path.stat().st_mtime_ns}"
    )
    assert codex_improvement_review_version_id(None) == CODEX_IMPROVEMENT_REVIEW_VERSION_ID
