from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskPredictionDemoRequest, TaskRecord
from backend.app.services.task_prediction_codex import (
    build_codex_prediction_response,
    read_prediction_output,
)


def _task(*, label_column: str | None = "target") -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-prediction",
        team_id="team-1",
        created_by="user-1",
        name="Prediction Task",
        description="Run Codex prediction.",
        label_column=label_column,
        created_at=now,
        updated_at=now,
    )


def _write_predict_script(workspace: Path, source: str) -> Path:
    output_dir = workspace / "output"
    output_dir.mkdir(parents=True)
    predict_path = output_dir / "predict.py"
    predict_path.write_text(source, encoding="utf-8")
    return predict_path


def test_build_codex_prediction_response_ignores_missing_predict_script(tmp_path: Path) -> None:
    payload = TaskPredictionDemoRequest(features={"age": 40})

    assert build_codex_prediction_response(_task(), payload, None) is None
    assert build_codex_prediction_response(_task(), payload, tmp_path / "workspace") is None


def test_build_codex_prediction_response_rejects_empty_feature_payload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    predict_path = _write_predict_script(workspace, "print('not called')\n")

    response = build_codex_prediction_response(
        _task(),
        TaskPredictionDemoRequest(features={"target": "yes"}),
        workspace,
    )

    assert response is not None
    assert response.supported is False
    assert response.prediction is None
    assert "预测输入为空" in response.detail
    assert response.command_hint == f"Codex predict path: {predict_path}"


def test_build_codex_prediction_response_calls_predict_script(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    predict_path = _write_predict_script(
        workspace,
        "\n".join(
            [
                "import argparse",
                "import csv",
                "",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--input', required=True)",
                "parser.add_argument('--output', required=True)",
                "args = parser.parse_args()",
                "",
                "with open(args.input, 'r', encoding='utf-8', newline='') as handle:",
                "    row = next(csv.DictReader(handle))",
                "",
                "with open(args.output, 'w', encoding='utf-8', newline='') as handle:",
                "    writer = csv.DictWriter(handle, fieldnames=['score', 'age'])",
                "    writer.writeheader()",
                "    writer.writerow({'score': int(row['age']) + 1, 'age': row['age']})",
                "",
            ]
        ),
    )

    response = build_codex_prediction_response(
        _task(),
        TaskPredictionDemoRequest(features={"age": 40, "target": "yes"}),
        workspace,
    )

    assert response is not None
    assert response.supported is True
    assert response.prediction == {
        "features": {"age": 40},
        "result": {"score": "41", "age": "40"},
        "code_path": str(predict_path),
    }
    assert str(predict_path) in response.command_hint


def test_build_codex_prediction_response_reports_predict_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    predict_path = _write_predict_script(
        workspace,
        "\n".join(
            [
                "import sys",
                "print('bad input', file=sys.stderr)",
                "sys.exit(3)",
                "",
            ]
        ),
    )

    response = build_codex_prediction_response(
        _task(),
        TaskPredictionDemoRequest(features={"age": 40}),
        workspace,
    )

    assert response is not None
    assert response.supported is False
    assert response.prediction is None
    assert "退出码 3" in response.detail
    assert "bad input" in response.detail
    assert response.command_hint == f"Codex predict path: {predict_path}"


def test_read_prediction_output_returns_first_csv_row(tmp_path: Path) -> None:
    output_path = tmp_path / "output.csv"
    output_path.write_text("\ufefflabel,score\nA,0.9\nB,0.1\n", encoding="utf-8")

    assert read_prediction_output(output_path) == {"label": "A", "score": "0.9"}
    assert read_prediction_output(tmp_path / "missing.csv") == {}
