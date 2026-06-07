from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.models.task import (
    RunAttempt,
    RunSummary,
    TaskRecord,
    TaskStatus,
    TokenUsageReport,
)
from backend.app.services.task_codex_token_ledger import sync_codex_token_ledger


class _FakeTaskStore:
    def __init__(self) -> None:
        self.ledger_rows: list[dict] = []

    def upsert_token_ledger(self, **kwargs) -> None:
        self.ledger_rows.append(kwargs)


class _FakeGovernanceStore:
    def __init__(self, settings, quota) -> None:
        self.settings = settings
        self.quota = quota

    def get_member_quota(self, team_id: str, user_id: str, *, access_token: str | None = None):
        return self.quota


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-codex-token-ledger",
        team_id="team-1",
        created_by="user-1",
        name="Codex token ledger",
        description="Ledger task.",
        status=TaskStatus.completed,
        executor_type="codex",
        created_at=now,
        updated_at=now,
    )


def _team_access():
    return SimpleNamespace(
        team_id="team-1",
        access_token="token",
        user=SimpleNamespace(id="user-1"),
    )


def test_sync_codex_token_ledger_uses_last_run_usage_and_returns_exhausted_quota() -> None:
    task = _task()
    task.last_run = RunSummary(
        best_model="ridge",
        metric_name="mae",
        metric_value=2.0,
        output_dir="workspace-1",
        token_usage=TokenUsageReport(input_tokens=10, output_tokens=5, total_tokens=15),
    )
    store = _FakeTaskStore()
    quota = SimpleNamespace(status="active", token_quota=100, token_remaining=0)

    with patch("backend.app.services.task_codex_token_ledger.get_settings", return_value=object()), patch(
        "backend.app.services.task_codex_token_ledger.read_model_profile",
        return_value={"display_name": "Codex model"},
    ), patch(
        "backend.app.services.task_codex_token_ledger.GovernanceStore",
        lambda settings: _FakeGovernanceStore(settings, quota),
    ):
        exhausted = sync_codex_token_ledger(store, task, _team_access())

    assert exhausted is True
    assert len(store.ledger_rows) == 1
    row = store.ledger_rows[0]
    assert row["phase"] == "codex"
    assert row["stage_key"] == "codex_native"
    assert row["source_key"] == "workspace-1"
    assert row["usage"].total_tokens == 15
    assert row["connector_display_name"] == "Codex model"
    assert row["calculation_method"] == "codex_app_server_token_usage"


def test_sync_codex_token_ledger_reads_workspace_usage_file(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    (output / "token_usage.json").write_text(
        '{"total":{"total_input_tokens":20,"total_output_tokens":7,"total_tokens":27}}',
        encoding="utf-8",
    )
    task = _task()
    task.last_run_attempt = RunAttempt(output_dir=str(workspace))
    store = _FakeTaskStore()
    quota = SimpleNamespace(status="active", token_quota=100, token_remaining=73)

    with patch("backend.app.services.task_codex_token_ledger.get_settings", return_value=object()), patch(
        "backend.app.services.task_codex_token_ledger.read_model_profile",
        return_value={"display_name": "Codex model"},
    ), patch(
        "backend.app.services.task_codex_token_ledger.GovernanceStore",
        lambda settings: _FakeGovernanceStore(settings, quota),
    ):
        exhausted = sync_codex_token_ledger(store, task, _team_access())

    assert exhausted is False
    assert store.ledger_rows[0]["source_key"] == str(workspace)
    assert store.ledger_rows[0]["usage"].total_tokens == 27


def test_sync_codex_token_ledger_skips_when_usage_is_missing() -> None:
    store = _FakeTaskStore()

    assert sync_codex_token_ledger(store, _task(), _team_access()) is False
    assert store.ledger_rows == []
