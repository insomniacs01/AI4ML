from __future__ import annotations

import ast
import csv
import importlib.util
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.models.task import TaskPredictionDemoRequest, TaskPredictionDemoResponse, TaskRecord
from backend.app.services.codex_backend import resolve_codex_workspace
from backend.app.services.task_artifacts import build_run_artifact_index
from backend.app.services.task_targets import target_columns_from_task

logger = logging.getLogger(__name__)


def build_prediction_demo_response(task: TaskRecord, payload: TaskPredictionDemoRequest) -> TaskPredictionDemoResponse:
    codex_response = _build_codex_prediction_response(task, payload)
    if codex_response is not None:
        return codex_response

    artifact_index = build_run_artifact_index(task, prefer_success=True)
    output_dir = artifact_index.output_dir
    if output_dir is None:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="当前任务还没有成功结果，无法提供试算入口。",
        )

    generated_code = artifact_index.generated_code_path
    if generated_code is None:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="最新结果目录中没有找到可直接使用的模型或生成代码，因此暂不支持试算。",
        )

    generated_response = _build_generated_code_prediction_response(task, payload, generated_code)
    if generated_response is not None:
        return generated_response

    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=False,
        detail=(
            "已找到真实训练代码，但生成代码没有暴露可调用的 predict(payload) 或 predict(features) 函数。"
            "为避免伪造预测结果，当前只返回可复用代码入口。"
        ),
        command_hint=f"Review and adapt {generated_code} with features: {json.dumps(payload.features, ensure_ascii=False)}",
    )


def _build_codex_prediction_response(
    task: TaskRecord,
    payload: TaskPredictionDemoRequest,
) -> TaskPredictionDemoResponse | None:
    workspace = resolve_codex_workspace(task, get_settings())
    if workspace is None:
        return None
    predict_path = workspace / "output" / "predict.py"
    if not predict_path.is_file():
        return None

    features = _clean_prediction_features(task, payload)
    if not features:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="预测输入为空，或只包含目标列。请传入至少一个特征字段。",
            command_hint=f"Codex predict path: {predict_path}",
        )

    try:
        with tempfile.TemporaryDirectory(prefix=f"ai4ml-codex-predict-{task.id}-") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.csv"
            output_path = temp_path / "output.csv"
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(features.keys()))
                writer.writeheader()
                writer.writerow(features)
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
                return TaskPredictionDemoResponse(
                    task_id=task.id,
                    supported=False,
                    detail=f"Codex predict.py 试算失败，退出码 {completed.returncode}：{detail[:800]}",
                    command_hint=f"Codex predict path: {predict_path}",
                )
            prediction = _read_prediction_output(output_path)
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


def _build_generated_code_prediction_response(
    task: TaskRecord,
    payload: TaskPredictionDemoRequest,
    generated_code: Path,
) -> TaskPredictionDemoResponse | None:
    if not _generated_code_has_predict_contract(generated_code):
        return None

    features = _clean_prediction_features(task, payload)
    if not features:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="预测输入为空，或只包含目标列。请传入至少一个特征字段。",
            command_hint=f"Generated code path: {generated_code}",
        )

    module, import_error = _load_generated_code_module(task, generated_code)
    if import_error is not None:
        return import_error
    if module is None:
        return None

    predict = getattr(module, "predict", None)
    if not callable(predict):
        return None

    prediction, prediction_error = _call_generated_predict(task, payload, generated_code, predict, features)
    if prediction_error is not None:
        return prediction_error

    probabilities = _call_generated_predict_proba(task, module, features)
    return _generated_code_prediction_success(task, generated_code, features, prediction, probabilities)


def _load_generated_code_module(
    task: TaskRecord,
    generated_code: Path,
) -> tuple[Any | None, TaskPredictionDemoResponse | None]:
    module_name = f"_ai4ml_generated_predict_{task.id}_{abs(hash(str(generated_code)))}"
    spec = importlib.util.spec_from_file_location(module_name, generated_code)
    if spec is None or spec.loader is None:
        return None, None

    previous_path = list(sys.path)
    sys.path.insert(0, str(generated_code.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        return None, _generated_code_import_error(task, generated_code, exc)
    finally:
        sys.path[:] = previous_path
    return module, None


def _generated_code_import_error(
    task: TaskRecord,
    generated_code: Path,
    exc: Exception,
) -> TaskPredictionDemoResponse:
    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=False,
        detail=f"已找到 generated_code.py，但导入生成代码失败，不能安全调用在线预测：{exc}",
        command_hint=f"Generated code path: {generated_code}",
    )


def _call_generated_predict(
    task: TaskRecord,
    payload: TaskPredictionDemoRequest,
    generated_code: Path,
    predict: Any,
    features: dict[str, Any],
) -> tuple[Any, TaskPredictionDemoResponse | None]:
    try:
        prediction = predict(features)
    except TypeError:
        try:
            prediction = predict(payload.features)
        except Exception as exc:  # noqa: BLE001
            return None, _generated_code_prediction_error(task, generated_code, exc)
    except Exception as exc:  # noqa: BLE001
        return None, _generated_code_prediction_error(task, generated_code, exc)
    return prediction, None


def _call_generated_predict_proba(task: TaskRecord, module: Any, features: dict[str, Any]) -> Any | None:
    predict_proba = getattr(module, "predict_proba", None)
    if not callable(predict_proba):
        return None
    try:
        return predict_proba(features)
    except Exception as exc:
        logger.debug("Generated predict_proba failed for task %s: %s", task.id, exc)
        return None


def _generated_code_prediction_success(
    task: TaskRecord,
    generated_code: Path,
    features: dict[str, Any],
    prediction: Any,
    probabilities: Any | None,
) -> TaskPredictionDemoResponse:
    result: dict[str, Any] = {
        "label": _json_safe_value(prediction),
        "features": features,
        "code_path": str(generated_code),
    }
    if probabilities is not None:
        result["probabilities"] = _json_safe_value(probabilities)
    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=True,
        detail="已调用 generated_code.py 中的真实 predict 函数完成单行在线预测。",
        prediction=result,
        command_hint=f"Generated code path: {generated_code}",
    )


def _generated_code_has_predict_contract(generated_code: Path) -> bool:
    try:
        tree = ast.parse(generated_code.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    has_predict = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            has_predict = has_predict or node.name == "predict"
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if _is_guarded_main_block(node):
            continue
        return False
    return has_predict


def _is_guarded_main_block(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left = test.left
    right = test.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


def _generated_code_prediction_error(
    task: TaskRecord,
    generated_code: Path,
    exc: Exception,
) -> TaskPredictionDemoResponse:
    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=False,
        detail=f"generated_code.py 暴露了 predict 函数，但本次调用失败：{exc}",
        command_hint=f"Generated code path: {generated_code}",
    )


def _clean_prediction_features(task: TaskRecord, payload: TaskPredictionDemoRequest) -> dict[str, Any]:
    target_columns = set(target_columns_from_task(task))
    return {
        key: value
        for key, value in payload.features.items()
        if key and key not in target_columns
    }


def _read_prediction_output(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[0] if rows else {}


def _json_safe_value(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception as exc:
            logger.debug("Could not coerce scalar JSON value %r: %s", value, exc)
            pass
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
