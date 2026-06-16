from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_http import CodexBackendClient, task_description


def _task() -> TaskRecord:
    now = datetime.now(timezone.utc)
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Task",
        description="Train a model",
        status=TaskStatus.running,
        executor_type="codex",
        dataset_path="D:/data/train.csv",
        codex_session_id="session-1",
        codex_thread_id="thread-1",
        codex_workspace_path="D:/workspaces/task-1",
        created_at=now,
        updated_at=now,
    )


def test_codex_start_payload_includes_token_budget(monkeypatch) -> None:
    client = CodexBackendClient(SimpleNamespace(codex_backend_url="http://127.0.0.1:3000"))
    calls = []
    monkeypatch.setattr(client, "post_json", lambda route, payload: calls.append((route, payload)) or {"ok": True})

    client.start_task(_task(), token_budget=123)

    assert calls[0][0] == "/api/ai4ml/tasks/start"
    assert calls[0][1]["tokenBudget"] == 123


def test_codex_resume_payload_omits_unlimited_token_budget(monkeypatch) -> None:
    client = CodexBackendClient(SimpleNamespace(codex_backend_url="http://127.0.0.1:3000"))
    calls = []
    monkeypatch.setattr(client, "post_json", lambda route, payload: calls.append((route, payload)) or {"ok": True})

    client.resume_task(_task(), token_budget=None)

    assert calls[0][0] == "/api/ai4ml/tasks/resume"
    assert "tokenBudget" not in calls[0][1]


def test_task_description_includes_acceptance_and_first_round_models() -> None:
    task = _task()
    task.problem_type = "regression"
    task.structured_requirements = {
        "target_columns_hint": ["Y1", "Y2"],
        "metric_name": "mean_rmse",
        "acceptance": {
            "primary_metric": "mean_rmse",
            "threshold": 6,
            "higher_is_better": False,
        },
        "improvement_policy": {"max_auto_improvement_rounds": 5},
        "initial_model_selection": {
            "planned_models_or_methods": ["Ridge", "RandomForestRegressor"],
        },
    }

    description = task_description(task)

    assert "目标列：Y1、Y2" in description
    assert "任务类型：regression" in description
    assert "用户成功标准：主指标 mean_rmse，成功阈值 6，越低越好" in description
    assert "最大自动改进轮数：5" in description
    assert "第一轮候选模型：Ridge, RandomForestRegressor" in description
