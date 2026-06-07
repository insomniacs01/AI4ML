from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.core.supabase_auth import SupabaseUser, TeamAccessContext
from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_codex_human_gates import CODEX_PLAN_APPROVAL_VERSION_ID
from backend.app.services.task_codex_human_requests import (
    ensure_codex_improvement_request,
    ensure_codex_plan_request,
)


class _FakeTaskStore:
    def __init__(self) -> None:
        self.requests: list[TaskHumanRequestRecord] = []
        self.created_kwargs: list[dict] = []
        self.updated_requests: list[TaskHumanRequestRecord] = []

    def list_human_requests(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str | None = None,
    ) -> list[TaskHumanRequestRecord]:
        return list(self.requests)

    def create_human_request(self, **kwargs) -> TaskHumanRequestRecord:
        self.created_kwargs.append(kwargs)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        request = TaskHumanRequestRecord(
            id=f"request-{len(self.created_kwargs)}",
            team_id=kwargs["team_id"],
            task_id=kwargs["task_id"],
            stage=kwargs["stage"],
            status=HumanInteractionRequestStatus.pending,
            version_id=kwargs.get("version_id"),
            payload=kwargs.get("payload"),
            created_at=now,
            updated_at=now,
        )
        self.requests.append(request)
        return request

    def update_human_request(
        self,
        request: TaskHumanRequestRecord,
        *,
        access_token: str | None = None,
    ) -> TaskHumanRequestRecord:
        self.updated_requests.append(request)
        return request


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-codex-human-requests",
        team_id="team-1",
        created_by="user-1",
        name="Codex human requests",
        description="Human request task.",
        status=TaskStatus.paused_for_review,
        codex_workspace_path="workspace",
        created_at=now,
        updated_at=now,
    )


def _team_access() -> TeamAccessContext:
    return TeamAccessContext(
        team_id="team-1",
        role="admin",
        user=SupabaseUser(id="user-1", email=None, raw={}),
        access_token="token",
    )


def test_ensure_codex_plan_request_creates_open_request() -> None:
    store = _FakeTaskStore()

    with patch("backend.app.services.task_codex_human_requests.get_task_store", return_value=store), patch(
        "backend.app.services.task_codex_human_requests.codex_plan_text",
        return_value="Plan text.",
    ):
        ensure_codex_plan_request(_task(), _team_access(), plan_path="workspace/output/plan.md")

    assert len(store.created_kwargs) == 1
    created = store.created_kwargs[0]
    assert created["stage"] == WorkflowStage.data_analysis
    assert created["version_id"] == CODEX_PLAN_APPROVAL_VERSION_ID
    assert created["payload"]["request_type"] == "codex_plan_approval"
    assert created["payload"]["plan_text"] == "Plan text."
    assert store.updated_requests[0].status == HumanInteractionRequestStatus.open


def test_ensure_codex_improvement_request_creates_open_request(tmp_path: Path) -> None:
    store = _FakeTaskStore()
    improvement_plan_path = tmp_path / "improvement_plan.md"
    improvement_plan_path.write_text("Improve validation.", encoding="utf-8")

    with patch("backend.app.services.task_codex_human_requests.get_task_store", return_value=store):
        ensure_codex_improvement_request(
            _task(),
            _team_access(),
            artifacts={"improvement_plan": "Improve validation."},
            improvement_plan_path=str(improvement_plan_path),
        )

    assert len(store.created_kwargs) == 1
    created = store.created_kwargs[0]
    assert created["stage"] == WorkflowStage.training_validation
    assert str(created["version_id"]).startswith("codex-improvement-review:")
    assert created["payload"]["request_type"] == "codex_improvement_review"
    assert created["payload"]["improvement_plan_text"] == "Improve validation."
    assert store.updated_requests[0].status == HumanInteractionRequestStatus.open


def test_ensure_codex_improvement_request_skips_without_plan_content() -> None:
    store = _FakeTaskStore()

    with patch("backend.app.services.task_codex_human_requests.get_task_store", return_value=store):
        ensure_codex_improvement_request(_task(), _team_access(), artifacts={}, improvement_plan_path=None)

    assert store.created_kwargs == []
    assert store.updated_requests == []
