from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.models.task import TaskPredictionDemoRequest, TaskRecord
from backend.app.services import codex_workspace_resolution, task_prediction
from backend.app.services.task_prediction import _build_generated_code_prediction_response


def _task(*, label_column: str | None = "target", structured_requirements: dict | None = None) -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-prediction",
        team_id="team-1",
        created_by="user-1",
        name="Prediction Task",
        description="Run generated prediction.",
        label_column=label_column,
        structured_requirements=structured_requirements,
        created_at=now,
        updated_at=now,
    )


def test_generated_code_prediction_response_calls_predict_and_predict_proba(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text(
        "\n".join(
            [
                "def predict(features):",
                "    return {'score': features['age'] + 1}",
                "",
                "def predict_proba(features):",
                "    return {'yes': 0.75, 'no': 0.25}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    response = _build_generated_code_prediction_response(
        _task(),
        TaskPredictionDemoRequest(features={"age": 40, "target": "yes"}),
        generated_code,
    )

    assert response is not None
    assert response.supported is True
    assert response.prediction["features"] == {"age": 40}
    assert response.prediction["label"] == {"score": 41}
    assert response.prediction["probabilities"] == {"yes": 0.75, "no": 0.25}
    assert response.prediction["code_path"] == str(generated_code)


def test_generated_code_prediction_response_rejects_empty_feature_payload(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text("def predict(features):\n    return 'yes'\n", encoding="utf-8")

    response = _build_generated_code_prediction_response(
        _task(),
        TaskPredictionDemoRequest(features={"target": "yes"}),
        generated_code,
    )

    assert response is not None
    assert response.supported is False
    assert response.prediction is None
    assert "预测输入为空" in response.detail


def test_generated_code_prediction_filters_structured_multi_targets(tmp_path: Path) -> None:
    generated_code = tmp_path / "generated_code.py"
    generated_code.write_text(
        "def predict(features):\n    return sorted(features.keys())\n",
        encoding="utf-8",
    )

    response = _build_generated_code_prediction_response(
        _task(label_column=None, structured_requirements={"target_columns_hint": ["Y1", "Y2"]}),
        TaskPredictionDemoRequest(features={"X1": 1, "Y1": 10, "Y2": 20}),
        generated_code,
    )

    assert response is not None
    assert response.supported is True
    assert response.prediction["features"] == {"X1": 1}
    assert response.prediction["label"] == ["X1"]


def test_prediction_demo_fast_path_does_not_scan_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        codex_workspace_root=tmp_path / "workspaces",
        run_output_dir=tmp_path / "runs",
    )
    task = _task()
    task.executor_type = "codex"
    task.codex_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def fail_if_full_workspace_scan_runs(*args: object, **kwargs: object) -> None:
        raise AssertionError("prediction demo must not scan the workspace root")

    monkeypatch.setattr(task_prediction, "get_settings", lambda: settings)
    monkeypatch.setattr(codex_workspace_resolution, "latest_started_workspace", fail_if_full_workspace_scan_runs)

    response = task_prediction.build_prediction_demo_response(
        task,
        TaskPredictionDemoRequest(features={"age": 40}),
    )

    assert response.supported is False
    assert "还没有成功结果" in response.detail
