from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.core.config import get_settings
from backend.app.models.task import TaskPredictionDemoRequest, TaskPredictionDemoResponse, TaskRecord
from backend.app.services.codex_workspace_resolution import resolve_known_codex_workspace_path
from backend.app.services.task_artifacts import build_run_artifact_index
from backend.app.services.task_prediction_codex import build_codex_prediction_response
from backend.app.services.task_prediction_generated_code import (
    GeneratedCodePrediction,
    GeneratedCodePredictionFailure,
    call_generated_code_prediction,
    generated_code_has_predict_contract,
)
from backend.app.services.task_prediction_inputs import clean_prediction_features


def build_prediction_demo_response(task: TaskRecord, payload: TaskPredictionDemoRequest) -> TaskPredictionDemoResponse:
    settings = get_settings()
    codex_response = _build_codex_prediction_response(task, payload, settings)
    if codex_response is not None:
        return codex_response

    artifact_index = build_run_artifact_index(task, settings=settings, prefer_success=True)
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
    settings: Settings,
) -> TaskPredictionDemoResponse | None:
    workspace = resolve_known_codex_workspace_path(task, settings)
    return build_codex_prediction_response(task, payload, workspace)


def _build_generated_code_prediction_response(
    task: TaskRecord,
    payload: TaskPredictionDemoRequest,
    generated_code: Path,
) -> TaskPredictionDemoResponse | None:
    if not generated_code_has_predict_contract(generated_code):
        return None

    features = clean_prediction_features(task, payload)
    if not features:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="预测输入为空，或只包含目标列。请传入至少一个特征字段。",
            command_hint=f"Generated code path: {generated_code}",
        )

    prediction, failure = call_generated_code_prediction(
        generated_code,
        task_id=task.id,
        features=features,
        fallback_features=payload.features,
    )
    if failure is not None:
        return _generated_code_failure_response(task, generated_code, failure)
    if prediction is None:
        return None

    return _generated_code_prediction_success(task, generated_code, features, prediction)


def _generated_code_failure_response(
    task: TaskRecord,
    generated_code: Path,
    failure: GeneratedCodePredictionFailure,
) -> TaskPredictionDemoResponse:
    if failure.kind == "import":
        detail = f"已找到 generated_code.py，但导入生成代码失败，不能安全调用在线预测：{failure.detail}"
    else:
        detail = f"generated_code.py 暴露了 predict 函数，但本次调用失败：{failure.detail}"
    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=False,
        detail=detail,
        command_hint=f"Generated code path: {generated_code}",
    )


def _generated_code_prediction_success(
    task: TaskRecord,
    generated_code: Path,
    features: dict[str, Any],
    prediction: GeneratedCodePrediction,
) -> TaskPredictionDemoResponse:
    result: dict[str, Any] = {
        "label": prediction.label,
        "features": features,
        "code_path": str(generated_code),
    }
    if prediction.probabilities is not None:
        result["probabilities"] = prediction.probabilities
    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=True,
        detail="已调用 generated_code.py 中的真实 predict 函数完成单行在线预测。",
        prediction=result,
        command_hint=f"Generated code path: {generated_code}",
    )
