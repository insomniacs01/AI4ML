from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import RunAttempt, RunSummary, TaskRecord, TaskStatus
from backend.app.services.task_chat import _build_task_context, _load_chat_history


def test_load_chat_history_filters_invalid_entries_and_normalizes_defaults() -> None:
    messages = _load_chat_history(
        [
            "invalid",
            {"role": "user", "content": "  "},
            {
                "id": "message-1",
                "role": "user",
                "origin": "unexpected",
                "status": "unexpected",
                "content": "  hello  ",
                "token_usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "message-2",
                "role": "assistant",
                "origin": "local_runtime",
                "status": "error",
                "content": " reply ",
                "model_name": "model-a",
                "composed_prompt": "prompt-a",
                "token_usage": "invalid",
                "created_at": "not-a-date",
            },
            {"role": "system", "content": "ignored"},
        ]
    )

    assert len(messages) == 2
    assert messages[0].id == "message-1"
    assert messages[0].role == "user"
    assert messages[0].origin == "user"
    assert messages[0].status == "ok"
    assert messages[0].content == "hello"
    assert messages[0].token_usage is not None
    assert messages[0].token_usage.total_tokens == 7
    assert messages[0].created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert messages[1].id == "message-2"
    assert messages[1].role == "assistant"
    assert messages[1].origin == "local_runtime"
    assert messages[1].status == "error"
    assert messages[1].content == "reply"
    assert messages[1].model_name == "model-a"
    assert messages[1].composed_prompt == "prompt-a"
    assert messages[1].token_usage is None
    assert messages[1].created_at is None


def test_load_chat_history_rejects_non_list_history() -> None:
    assert _load_chat_history({"role": "user", "content": "hello"}) == []


def test_build_task_context_formats_analysis_fields_and_prefers_latest_attempt_output() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    task = TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Revenue model",
        description="Predict revenue.",
        label_column="revenue",
        problem_type="regression",
        status=TaskStatus.running,
        dataset_filename="train.csv",
        notes="Use robust validation.",
        structured_requirements={
            "metric_name": "mae",
            "reasoning": "Regression target.",
            "column_names": ["region", "revenue"],
            "preview_rows": [
                {"region": "A", "revenue": 1},
                {"region": "B", "revenue": 2},
                {"region": "C", "revenue": 3},
                {"region": "D", "revenue": 4},
            ],
        },
        last_run=RunSummary(best_model="baseline", metric_name="mae", metric_value=3.0, output_dir="run-output"),
        last_run_attempt=RunAttempt(output_dir="attempt-output"),
        created_at=now,
        updated_at=now,
    )

    context = _build_task_context(task)

    assert "- Task name: Revenue model" in context
    assert "- Dataset filename: train.csv" in context
    assert "- Suggested metric: mae" in context
    assert "- Task status: running" in context
    assert "- Latest run output dir: attempt-output" in context
    assert '- CSV columns: ["region", "revenue"]' in context
    assert '"region": "A"' in context
    assert '"region": "D"' not in context
    assert "Human node parameters - data analysis: target column=revenue; problem type=regression; primary metric=mae." in context
