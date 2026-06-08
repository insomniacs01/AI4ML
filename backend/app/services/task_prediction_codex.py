from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.app.models.task import TaskPredictionDemoRequest, TaskPredictionDemoResponse, TaskRecord
from backend.app.services.task_prediction_inputs import clean_prediction_features


class CodexPredictProcessError(Exception):
    def __init__(self, returncode: int, detail: str) -> None:
        super().__init__(detail)
        self.returncode = returncode
        self.detail = detail


def build_codex_prediction_response(
    task: TaskRecord,
    payload: TaskPredictionDemoRequest,
    workspace: Path | None,
) -> TaskPredictionDemoResponse | None:
    if workspace is None:
        return None
    predict_path = workspace / "output" / "predict.py"
    if not predict_path.is_file():
        return None

    features = clean_prediction_features(task, payload)
    if not features:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="预测输入为空，或只包含目标列。请传入至少一个特征字段。",
            command_hint=f"Codex predict path: {predict_path}",
        )

    try:
        prediction = run_codex_predict(predict_path, task.id, features)
    except CodexPredictProcessError as exc:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail=f"Codex predict.py 试算失败，退出码 {exc.returncode}：{exc.detail[:800]}",
            command_hint=f"Codex predict path: {predict_path}",
        )
    except Exception as exc:  # noqa: BLE001
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail=f"调用 Codex predict.py 失败：{exc}",
            command_hint=f"Codex predict path: {predict_path}",
        )

    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=True,
        detail="已调用 Codex workspace 中的真实 predict.py 完成单行试算。",
        prediction={
            "features": features,
            "result": prediction,
            "code_path": str(predict_path),
        },
        command_hint=f"{sys.executable} {predict_path} --input input.csv --output output.csv",
    )


def run_codex_predict(predict_path: Path, task_id: str, features: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"ai4ml-codex-predict-{task_id}-") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "input.csv"
        output_path = temp_path / "output.csv"
        write_prediction_input(input_path, features)
        completed = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(predict_path),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ],
            cwd=str(predict_path.parent),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise CodexPredictProcessError(completed.returncode, detail)
        return read_prediction_output(output_path)


def write_prediction_input(path: Path, features: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(features.keys()))
        writer.writeheader()
        writer.writerow(features)


def read_prediction_output(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[0] if rows else {}
