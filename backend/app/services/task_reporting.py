from __future__ import annotations

import ast
import csv
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import (
    DatasetProfile,
    FeatureImportanceEntry,
    TaskModelReportResponse,
    TaskPredictionDemoRequest,
    TaskPredictionDemoResponse,
    TaskRecord,
)
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_from_plain


FEATURE_IMPORTANCE_FILENAMES = {
    "feature_importance.csv",
    "feature_importance.json",
    "feature_importances.csv",
    "feature_importances.json",
}
NODE_SCAN_LIMIT = 16


def build_task_model_report(task: TaskRecord) -> TaskModelReportResponse:
    dataset_profile = _resolve_dataset_profile(task)
    feature_importance, feature_paths = _collect_feature_importance(task)
    result_summary = _build_result_summary(task)
    data_quality_notes = _build_data_quality_notes(dataset_profile)
    limitation_notes = _build_limitation_notes(task, dataset_profile, feature_importance)
    generated_at = datetime.now(timezone.utc)

    return TaskModelReportResponse(
        task_id=task.id,
        task_name=task.name,
        generated_at=generated_at,
        dataset_profile=dataset_profile,
        feature_importance=feature_importance,
        result_summary=result_summary,
        data_quality_notes=data_quality_notes,
        limitation_notes=limitation_notes,
        artifact_paths=feature_paths,
        report_markdown=_build_report_markdown(
            task=task,
            generated_at=generated_at,
            dataset_profile=dataset_profile,
            feature_importance=feature_importance,
            result_summary=result_summary,
            data_quality_notes=data_quality_notes,
            limitation_notes=limitation_notes,
        ),
    )


def build_prediction_demo_response(task: TaskRecord, payload: TaskPredictionDemoRequest) -> TaskPredictionDemoResponse:
    output_dir = _resolve_run_output_dir(task)
    if output_dir is None:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="当前任务还没有成功运行产物，无法提供在线预测入口。",
        )

    predictor_dir = _find_autogluon_predictor_dir(output_dir)
    if predictor_dir is not None:
        return _build_autogluon_prediction_response(task, payload, predictor_dir)

    generated_code = _find_generated_code(output_dir)
    if generated_code is None:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="最新运行目录中没有找到可复用的 AutoGluon predictor.pkl 或 generated_code.py，因此暂不支持在线预测。",
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


def _build_autogluon_prediction_response(
    task: TaskRecord,
    payload: TaskPredictionDemoRequest,
    predictor_dir: Path,
) -> TaskPredictionDemoResponse:
    features = _clean_prediction_features(task, payload)
    if not features:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="预测输入为空，或只包含目标列。请传入至少一个特征字段。",
            command_hint=f"AutoGluon predictor path: {predictor_dir}",
        )

    try:
        import pandas as pd
        from autogluon.tabular import TabularPredictor
    except ImportError as exc:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail=f"已找到真实 AutoGluon 模型，但当前后端环境缺少在线预测依赖：{exc}",
            command_hint=f"AutoGluon predictor path: {predictor_dir}",
        )

    try:
        predictor = TabularPredictor.load(str(predictor_dir))
        frame = pd.DataFrame([features])
        prediction_series = predictor.predict(frame)
        prediction_value = _json_safe_value(
            prediction_series.iloc[0] if hasattr(prediction_series, "iloc") else prediction_series[0]
        )
        probabilities = None
        try:
            probabilities_frame = predictor.predict_proba(frame)
            if hasattr(probabilities_frame, "iloc"):
                probabilities = {
                    str(key): _json_safe_value(value)
                    for key, value in probabilities_frame.iloc[0].to_dict().items()
                }
        except Exception:
            probabilities = None
    except Exception as exc:  # noqa: BLE001
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail=f"已找到真实 AutoGluon 模型，但本次在线预测失败：{exc}",
            command_hint=f"AutoGluon predictor path: {predictor_dir}",
        )

    result: dict[str, Any] = {
        "label": prediction_value,
        "features": features,
        "model_path": str(predictor_dir),
    }
    if probabilities is not None:
        result["probabilities"] = probabilities
    return TaskPredictionDemoResponse(
        task_id=task.id,
        supported=True,
        detail="已使用最新运行产物中的真实 AutoGluon TabularPredictor 完成单行在线预测。",
        prediction=result,
        command_hint=f"AutoGluon predictor path: {predictor_dir}",
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

    module_name = f"_ai4ml_generated_predict_{task.id}_{abs(hash(str(generated_code)))}"
    spec = importlib.util.spec_from_file_location(module_name, generated_code)
    if spec is None or spec.loader is None:
        return None

    previous_path = list(sys.path)
    sys.path.insert(0, str(generated_code.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail=f"已找到 generated_code.py，但导入生成代码失败，不能安全调用在线预测：{exc}",
            command_hint=f"Generated code path: {generated_code}",
        )
    finally:
        sys.path[:] = previous_path

    predict = getattr(module, "predict", None)
    if not callable(predict):
        return None

    try:
        prediction = predict(features)
    except TypeError:
        try:
            prediction = predict(payload.features)
        except Exception as exc:  # noqa: BLE001
            return _generated_code_prediction_error(task, generated_code, exc)
    except Exception as exc:  # noqa: BLE001
        return _generated_code_prediction_error(task, generated_code, exc)

    probabilities = None
    predict_proba = getattr(module, "predict_proba", None)
    if callable(predict_proba):
        try:
            probabilities = predict_proba(features)
        except Exception:
            probabilities = None

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
    return {
        key: value
        for key, value in payload.features.items()
        if key and key != task.label_column
    }


def _resolve_dataset_profile(task: TaskRecord) -> DatasetProfile | None:
    if task.dataset_profile is not None:
        return task.dataset_profile
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    cached = dataset_profile_from_plain(structured.get("dataset_profile"))
    if cached is not None:
        return cached
    if not task.dataset_path:
        return None
    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists():
        return None
    return build_dataset_profile(
        dataset_path,
        filename=task.dataset_filename,
        target_column=task.label_column,
    )


def _collect_feature_importance(task: TaskRecord) -> tuple[list[FeatureImportanceEntry], list[str]]:
    output_dir = _resolve_run_output_dir(task)
    if output_dir is None:
        return [], []

    entries: list[FeatureImportanceEntry] = []
    paths: list[str] = []
    for path in _candidate_feature_importance_paths(output_dir):
        if not path.is_file():
            continue
        parsed = _parse_feature_importance_file(path)
        if parsed:
            entries.extend(parsed)
            paths.append(str(path))

    deduped: dict[str, FeatureImportanceEntry] = {}
    for entry in entries:
        current = deduped.get(entry.feature)
        if current is None or abs(entry.importance) > abs(current.importance):
            deduped[entry.feature] = entry

    return sorted(deduped.values(), key=lambda item: abs(item.importance), reverse=True)[:20], paths


def _parse_feature_importance_file(path: Path) -> list[FeatureImportanceEntry]:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            return _parse_feature_importance_payload(payload, source=str(path))
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return _parse_feature_importance_payload(rows, source=str(path))
    except Exception:
        return []


def _parse_feature_importance_payload(payload: Any, *, source: str) -> list[FeatureImportanceEntry]:
    rows: list[Any]
    if isinstance(payload, dict):
        if isinstance(payload.get("feature_importance"), list):
            rows = payload["feature_importance"]
        elif isinstance(payload.get("features"), list):
            rows = payload["features"]
        else:
            rows = [{"feature": key, "importance": value} for key, value in payload.items()]
    elif isinstance(payload, list):
        rows = payload
    else:
        return []

    entries: list[FeatureImportanceEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        feature = row.get("feature") or row.get("feature_name") or row.get("name") or row.get("column")
        importance = row.get("importance") or row.get("score") or row.get("value")
        try:
            numeric_importance = float(importance)
        except (TypeError, ValueError):
            continue
        if isinstance(feature, str) and feature.strip():
            entries.append(FeatureImportanceEntry(feature=feature.strip(), importance=numeric_importance, source=source))
    return entries


def _build_result_summary(task: TaskRecord) -> list[str]:
    if not task.last_run:
        return ["当前任务还没有成功的 MLZero 运行结果。"]
    leaderboard_count = len(task.last_run.leaderboard or [])
    return [
        f"最佳模型为 {task.last_run.best_model}。",
        f"主要指标 {task.last_run.metric_name} = {task.last_run.metric_value:.6g}。",
        f"本次成功解析到 {leaderboard_count} 个候选模型结果。",
        f"运行产物目录：{task.last_run.output_dir}。",
    ]


def _build_data_quality_notes(profile: DatasetProfile | None) -> list[str]:
    if profile is None:
        return ["当前没有可读取的数据集画像。"]
    notes = [
        f"数据集包含 {profile.row_count} 行、{profile.column_count} 列。",
    ]
    columns_with_missing = [column for column in profile.columns if column.missing_count > 0]
    if columns_with_missing:
        worst = sorted(columns_with_missing, key=lambda item: item.missing_ratio, reverse=True)[:5]
        notes.append(
            "存在缺失值的字段包括："
            + "、".join(f"{item.name}({item.missing_ratio:.1%})" for item in worst)
            + "。"
        )
    else:
        notes.append("预览范围内未发现缺失值。")
    if profile.target_column:
        notes.append(f"当前目标列为 {profile.target_column}。")
    return notes


def _build_limitation_notes(
    task: TaskRecord,
    profile: DatasetProfile | None,
    feature_importance: list[FeatureImportanceEntry],
) -> list[str]:
    notes: list[str] = []
    if profile is not None and profile.row_count < 100:
        notes.append("数据行数较少，验证指标可能对划分方式敏感。")
    if not feature_importance:
        notes.append("当前运行产物中没有可解析的特征重要性文件，因此报告不展示特征排名。")
    if task.last_run and len(task.last_run.leaderboard or []) <= 1:
        notes.append("候选模型数量较少，模型选择结论的稳定性有限。")
    if not notes:
        notes.append("当前报告仅基于最近一次成功运行产物，不代表生产环境长期表现。")
    return notes


def _build_report_markdown(
    *,
    task: TaskRecord,
    generated_at: datetime,
    dataset_profile: DatasetProfile | None,
    feature_importance: list[FeatureImportanceEntry],
    result_summary: list[str],
    data_quality_notes: list[str],
    limitation_notes: list[str],
) -> str:
    lines = [
        f"# {task.name} 模型分析报告",
        "",
        f"- 生成时间：{generated_at.isoformat()}",
        f"- 任务类型：{task.problem_type or '未解析'}",
        f"- 目标列：{task.label_column or '未解析'}",
        "",
        "## 数据质量",
        *[f"- {item}" for item in data_quality_notes],
        "",
        "## 结果摘要",
        *[f"- {item}" for item in result_summary],
    ]
    if feature_importance:
        lines.extend([
            "",
            "## 特征重要性",
            *[f"- {item.feature}: {item.importance:.6g}" for item in feature_importance[:10]],
        ])
    if dataset_profile is not None:
        lines.extend([
            "",
            "## 字段概览",
            *[
                f"- {column.name}: {column.inferred_type}, 缺失 {column.missing_count}/{dataset_profile.row_count}"
                for column in dataset_profile.columns[:30]
            ],
        ])
    lines.extend([
        "",
        "## 风险和局限",
        *[f"- {item}" for item in limitation_notes],
    ])
    return "\n".join(lines)


def _resolve_run_output_dir(task: TaskRecord) -> Path | None:
    output_dir = None
    if task.last_run and task.last_run.output_dir:
        output_dir = Path(task.last_run.output_dir)
    elif task.last_run_attempt and task.last_run_attempt.output_dir:
        output_dir = Path(task.last_run_attempt.output_dir)
    if output_dir is None or not output_dir.exists():
        return None
    return output_dir


def _find_generated_code(output_dir: Path) -> Path | None:
    candidates = [
        output_dir / "generated_code.py",
        output_dir / "best_run" / "generated_code.py",
        *[node_dir / "generated_code.py" for node_dir in _recent_node_dirs(output_dir)],
        *[node_dir / "states" / "python_code.py" for node_dir in _recent_node_dirs(output_dir)],
    ]
    return next((path for path in candidates if path.is_file()), None)


def _find_autogluon_predictor_dir(output_dir: Path) -> Path | None:
    candidates = [
        path.parent
        for path in [
            output_dir / "predictor.pkl",
            output_dir / "best_run" / "predictor.pkl",
            output_dir / "best_run" / "output" / "predictor.pkl",
            *[node_dir / "predictor.pkl" for node_dir in _recent_node_dirs(output_dir)],
            *[node_dir / "output" / "predictor.pkl" for node_dir in _recent_node_dirs(output_dir)],
        ]
        if path.is_file()
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def _candidate_feature_importance_paths(output_dir: Path) -> list[Path]:
    dirs = [output_dir, output_dir / "best_run", output_dir / "best_run" / "output"]
    for node_dir in _recent_node_dirs(output_dir):
        dirs.extend([node_dir, node_dir / "output"])
    return [
        directory / filename
        for directory in dirs
        for filename in FEATURE_IMPORTANCE_FILENAMES
    ]


def _recent_node_dirs(output_dir: Path, *, limit: int = NODE_SCAN_LIMIT) -> list[Path]:
    try:
        node_dirs = [path for path in output_dir.iterdir() if path.is_dir() and path.name.startswith("node_")]
    except OSError:
        return []
    return sorted(node_dirs, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)[:limit]


def _json_safe_value(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
