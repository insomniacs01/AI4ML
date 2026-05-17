from __future__ import annotations

import ast
import csv
import importlib.util
import json
import math
import sys
from collections import Counter
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
from backend.app.services.task_artifacts import build_run_artifact_index
from backend.app.services.task_agent_loop import refresh_agent_loop_after_analysis, refresh_agent_loop_after_run


MAX_RELATIONSHIP_ROWS = 20_000
MAX_TARGET_PROFILE_ROWS = 50_000
MAX_CATEGORICAL_VALUES = 80
MIN_RELATIONSHIP_PAIRS = 3
REPORT_LOWER_IS_BETTER_METRICS = {
    "rmse",
    "root_mean_squared_error",
    "mse",
    "mean_squared_error",
    "mae",
    "mean_absolute_error",
    "median_absolute_error",
    "log_loss",
    "pinball_loss",
}


def build_task_model_report(task: TaskRecord) -> TaskModelReportResponse:
    dataset_profile = _resolve_dataset_profile(task)
    if dataset_profile is not None and task.dataset_profile is None:
        task.dataset_profile = dataset_profile
    _ensure_agent_loop_for_report(task)
    artifact_feature_importance, feature_paths = _collect_feature_importance(task)
    relationship_importance, relationship_notes = _collect_feature_relationships(task, dataset_profile)
    feature_importance = artifact_feature_importance or relationship_importance
    result_summary = _build_result_summary(
        task,
        feature_importance=feature_importance,
        relationship_notes=relationship_notes,
        using_artifact_importance=bool(artifact_feature_importance),
    )
    data_quality_notes = _build_data_quality_notes(dataset_profile)
    limitation_notes = _build_limitation_notes(
        task,
        dataset_profile,
        feature_importance,
        relationship_notes=relationship_notes,
        using_artifact_importance=bool(artifact_feature_importance),
    )
    generated_at = datetime.now(timezone.utc)

    return TaskModelReportResponse(
        task_id=task.id,
        task_name=task.name,
        generated_at=generated_at,
        dataset_profile=dataset_profile,
        feature_importance=feature_importance,
        result_summary=result_summary,
        data_quality_notes=data_quality_notes,
        relationship_notes=relationship_notes,
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
            relationship_notes=relationship_notes,
            using_artifact_importance=bool(artifact_feature_importance),
        ),
    )


def build_prediction_demo_response(task: TaskRecord, payload: TaskPredictionDemoRequest) -> TaskPredictionDemoResponse:
    artifact_index = build_run_artifact_index(task, prefer_success=True)
    output_dir = artifact_index.output_dir
    if output_dir is None:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail="当前任务还没有成功结果，无法提供试算入口。",
        )

    predictor_dir = artifact_index.predictor_dir
    if predictor_dir is not None:
        return _build_autogluon_prediction_response(task, payload, predictor_dir)

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
            command_hint=f"模型路径：{predictor_dir}",
        )

    try:
        import pandas as pd
        from autogluon.tabular import TabularPredictor
    except ImportError as exc:
        return TaskPredictionDemoResponse(
            task_id=task.id,
            supported=False,
            detail=f"已找到真实模型，但当前后端环境缺少试算所需依赖：{exc}",
            command_hint=f"模型路径：{predictor_dir}",
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
            detail=f"已找到真实模型，但本次试算失败：{exc}",
            command_hint=f"模型路径：{predictor_dir}",
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
        detail="已使用最新结果中的真实模型完成单行试算。",
        prediction=result,
        command_hint=f"模型路径：{predictor_dir}",
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
    artifact_index = build_run_artifact_index(task, prefer_success=True)
    if artifact_index.output_dir is None:
        return [], []

    entries: list[FeatureImportanceEntry] = []
    paths: list[str] = []
    for path in artifact_index.feature_importance_paths:
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


def _collect_feature_relationships(
    task: TaskRecord,
    profile: DatasetProfile | None,
) -> tuple[list[FeatureImportanceEntry], list[str]]:
    target_column = task.label_column or (profile.target_column if profile else None)
    if not target_column or not task.dataset_path:
        return [], ["缺少目标列或数据集路径，无法计算特征与目标列的关系。"]
    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists():
        return [], ["数据集文件不存在，无法计算特征与目标列的关系。"]

    rows: list[dict[str, str]] = []
    try:
        with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or target_column not in reader.fieldnames:
                return [], [f"数据集中没有找到目标列 {target_column}，无法计算特征与目标列的关系。"]
            for index, row in enumerate(reader):
                if index >= MAX_RELATIONSHIP_ROWS:
                    break
                rows.append(row)
    except OSError as exc:
        return [], [f"读取数据集失败，无法计算特征与目标列的关系：{exc}"]
    if not rows:
        return [], ["数据集没有可分析的数据行，无法计算特征与目标列的关系。"]

    target_values = [_clean_cell(row.get(target_column)) for row in rows]
    target_numeric = [_to_float(value) for value in target_values]
    target_is_numeric = _usable_numeric_count(target_numeric) >= MIN_RELATIONSHIP_PAIRS
    entries: list[FeatureImportanceEntry] = []
    notes: list[str] = []

    for feature in reader.fieldnames or []:
        if feature == target_column:
            continue
        values = [_clean_cell(row.get(feature)) for row in rows]
        numeric_values = [_to_float(value) for value in values]
        source = "dataset_correlation"
        score: float | None = None
        method = ""
        if target_is_numeric and _usable_numeric_count(numeric_values) >= MIN_RELATIONSHIP_PAIRS:
            score = _absolute_pearson(numeric_values, target_numeric)
            method = "Pearson 线性相关"
        elif target_is_numeric:
            score = _categorical_target_eta(values, target_numeric)
            method = "类别分组解释度"
            source = "dataset_group_effect"
        elif _usable_numeric_count(numeric_values) >= MIN_RELATIONSHIP_PAIRS:
            score = _numeric_feature_categorical_target_eta(numeric_values, target_values)
            method = "按目标类别的数值分组差异"
            source = "dataset_group_effect"
        else:
            score = _cramers_v(values, target_values)
            method = "Cramer's V 类别关联"
            source = "dataset_categorical_association"
        if score is None or not math.isfinite(score):
            continue
        entries.append(FeatureImportanceEntry(feature=feature, importance=score, source=source))
        if score >= 0.75:
            strength = "强"
        elif score >= 0.45:
            strength = "中等"
        elif score >= 0.2:
            strength = "较弱"
        else:
            strength = "很弱"
        notes.append(f"{feature} 与目标列 {target_column} 的{method}为 {score:.3f}，属于{strength}关系。")

    entries = sorted(entries, key=lambda item: abs(item.importance), reverse=True)[:20]
    if not entries:
        return [], ["未找到足够的数值或可分组字段来计算稳定的特征关系。"]
    top_names = "、".join(item.feature for item in entries[:5])
    return entries, [f"按与目标列 {target_column} 的关系强度排序，当前最相关的特征是：{top_names}。", *notes[:10]]


def _clean_cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _to_float(value: str) -> float | None:
    if value == "":
        return None
    try:
        numeric = float(value)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def _usable_numeric_count(values: list[float | None]) -> int:
    return sum(1 for value in values if value is not None)


def _absolute_pearson(feature_values: list[float | None], target_values: list[float | None]) -> float | None:
    pairs = [(feature, target) for feature, target in zip(feature_values, target_values) if feature is not None and target is not None]
    if len(pairs) < MIN_RELATIONSHIP_PAIRS:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    var_x = sum((value - mean_x) ** 2 for value in xs)
    var_y = sum((value - mean_y) ** 2 for value in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    return abs(covariance / math.sqrt(var_x * var_y))


def _categorical_target_eta(feature_values: list[str], target_values: list[float | None]) -> float | None:
    groups: dict[str, list[float]] = {}
    for feature, target in zip(feature_values, target_values):
        if target is None or feature == "":
            continue
        groups.setdefault(feature, []).append(target)
        if len(groups) > MAX_CATEGORICAL_VALUES:
            return None
    groups = {key: values for key, values in groups.items() if values}
    if len(groups) < 2:
        return None
    all_values = [value for values in groups.values() for value in values]
    if len(all_values) < MIN_RELATIONSHIP_PAIRS:
        return None
    grand_mean = sum(all_values) / len(all_values)
    total_ss = sum((value - grand_mean) ** 2 for value in all_values)
    if total_ss <= 0:
        return None
    between_ss = sum(len(values) * ((sum(values) / len(values)) - grand_mean) ** 2 for values in groups.values())
    return math.sqrt(max(0.0, min(1.0, between_ss / total_ss)))


def _numeric_feature_categorical_target_eta(feature_values: list[float | None], target_values: list[str]) -> float | None:
    groups: dict[str, list[float]] = {}
    for feature, target in zip(feature_values, target_values):
        if feature is None or target == "":
            continue
        groups.setdefault(target, []).append(feature)
        if len(groups) > MAX_CATEGORICAL_VALUES:
            return None
    groups = {key: values for key, values in groups.items() if values}
    if len(groups) < 2:
        return None
    all_values = [value for values in groups.values() for value in values]
    if len(all_values) < MIN_RELATIONSHIP_PAIRS:
        return None
    grand_mean = sum(all_values) / len(all_values)
    total_ss = sum((value - grand_mean) ** 2 for value in all_values)
    if total_ss <= 0:
        return None
    between_ss = sum(len(values) * ((sum(values) / len(values)) - grand_mean) ** 2 for values in groups.values())
    return math.sqrt(max(0.0, min(1.0, between_ss / total_ss)))


def _cramers_v(feature_values: list[str], target_values: list[str]) -> float | None:
    table: dict[str, dict[str, int]] = {}
    row_totals: dict[str, int] = {}
    column_totals: dict[str, int] = {}
    total = 0
    for feature, target in zip(feature_values, target_values):
        if feature == "" or target == "":
            continue
        table.setdefault(feature, {})
        table[feature][target] = table[feature].get(target, 0) + 1
        row_totals[feature] = row_totals.get(feature, 0) + 1
        column_totals[target] = column_totals.get(target, 0) + 1
        total += 1
        if len(row_totals) > MAX_CATEGORICAL_VALUES or len(column_totals) > MAX_CATEGORICAL_VALUES:
            return None
    if total < MIN_RELATIONSHIP_PAIRS or len(row_totals) < 2 or len(column_totals) < 2:
        return None
    chi_square = 0.0
    for feature, row_total in row_totals.items():
        for target, column_total in column_totals.items():
            expected = row_total * column_total / total
            if expected <= 0:
                continue
            observed = table.get(feature, {}).get(target, 0)
            chi_square += (observed - expected) ** 2 / expected
    denominator = total * min(len(row_totals) - 1, len(column_totals) - 1)
    if denominator <= 0:
        return None
    return math.sqrt(max(0.0, min(1.0, chi_square / denominator)))


def _build_result_summary(
    task: TaskRecord,
    *,
    feature_importance: list[FeatureImportanceEntry],
    relationship_notes: list[str],
    using_artifact_importance: bool,
) -> list[str]:
    if not task.last_run:
        return [
            "当前任务还没有成功的自动建模结果；本报告只能给出数据与特征关系诊断，不能作为最终模型验收报告。",
            *relationship_notes[:3],
        ]
    leaderboard_count = len(task.last_run.leaderboard or [])
    summary = [
        f"最佳模型为 {task.last_run.best_model}。",
        f"主要指标 {task.last_run.metric_name} = {task.last_run.metric_value:.6g}。",
        f"本次成功解析到 {leaderboard_count} 个候选模型结果。",
        f"结果文件目录：{task.last_run.output_dir}。",
    ]
    if feature_importance:
        source_label = "模型给出的特征重要性" if using_artifact_importance else "数据集与目标列相关性分析"
        summary.append(f"按{source_label}看，最重要/最相关的特征包括：{_format_top_features(feature_importance)}。")
    else:
        summary.append("当前没有可量化的特征重要性或相关性结果，模型解释性不足。")
    return summary


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
    *,
    relationship_notes: list[str],
    using_artifact_importance: bool,
) -> list[str]:
    notes: list[str] = []
    if profile is not None and profile.row_count < 100:
        notes.append("数据行数较少，验证指标可能对划分方式敏感。")
    if not feature_importance:
        notes.append("当前没有可解析的特征重要性文件，也无法从数据集中计算稳定的特征关系，因此模型解释性不足。")
    elif not using_artifact_importance:
        notes.append("当前报告没有拿到模型给出的特征重要性；特征排名来自数据集和目标列的统计关系，只说明相关性，不等价于因果关系。")
    if relationship_notes and relationship_notes[0].startswith("未找到"):
        notes.append(relationship_notes[0])
    if task.last_run and len(task.last_run.leaderboard or []) <= 1:
        notes.append("候选模型数量较少，模型选择结论的稳定性有限。")
    if not notes:
        notes.append("当前报告仅基于最近一次成功结果，不代表生产环境长期表现。")
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
    relationship_notes: list[str],
    using_artifact_importance: bool,
) -> str:
    agent_loop = _agent_loop(task)
    target_profile = _build_target_profile(task, dataset_profile)
    artifact_index = build_run_artifact_index(task, prefer_success=True)
    primary_metric = _primary_metric_text(task)
    candidate_count = len(task.last_run.leaderboard or []) if task.last_run else 0
    lines = [
        f"# {task.name} 自动建模实验报告",
        "",
        "## 基本信息",
        "",
        f"- 生成时间：{generated_at.isoformat()}",
        f"- 数据文件：{task.dataset_filename or '未记录'}",
        f"- 运行结论：{_run_conclusion(task)}",
        f"- 任务类型：{task.problem_type or '未解析'}",
        f"- 目标列：{task.label_column or '未解析'}",
        f"- 主指标：{primary_metric}",
        f"- 报告口径：{_report_scope_text(using_artifact_importance)}",
        f"- 成功运行目录：{task.last_run.output_dir if task.last_run else '暂无'}",
        "",
        "---",
        "",
        "## 摘要",
        "",
        *_abstract_lines(task, dataset_profile, agent_loop, feature_importance, candidate_count),
        "",
        "---",
        "",
        "## 1. 任务背景与目标",
        "",
        *_task_background_lines(task, dataset_profile, target_profile),
        "",
        "## 2. 数据整理与质量检查",
        "",
        "### 2.1 数据集概览",
        "",
        *_dataset_overview_lines(dataset_profile, target_profile),
        "",
        "### 2.2 字段与缺失情况",
        "",
        *_field_quality_table_lines(dataset_profile),
        "",
        "### 2.3 数据质量结论",
        "",
        *[f"- {item}" for item in data_quality_notes],
        "",
        "## 3. 自动建模过程与检查清单",
        "",
        "### 3.1 执行流程",
        "",
        *_workflow_report_lines(agent_loop),
        "",
        "### 3.2 检查清单",
        "",
        *_checklist_report_lines(agent_loop),
        "",
        "## 4. 简单对照实验",
        "",
        *_baseline_experiment_lines(agent_loop, task),
        "",
        "## 5. 自动建模实验",
        "",
        "### 5.1 运行结果摘要",
        "",
        *[f"- {item}" for item in result_summary],
        "",
        "### 5.2 候选模型对比",
        "",
        *_model_result_lines(task),
        "",
        "### 5.3 生成文件",
        "",
        *_artifact_report_lines(artifact_index),
    ]
    if agent_loop:
        lines.extend([
            "",
            "## 6. 结果检查与优化过程",
            "",
            "### 6.1 结果检查",
            "",
            *_quality_gate_report_lines(agent_loop),
            "",
            "### 6.2 优化记录",
            "",
            *_tuning_attempt_report_lines(agent_loop),
            "",
            "### 6.3 停止条件",
            "",
            *_stop_condition_report_lines(agent_loop),
        ])
    else:
        lines.extend([
            "",
            "## 6. 结果检查与优化过程",
            "",
            "- 当前任务尚未记录完整检查数据，无法输出简单对照、结果检查和优化复盘。",
        ])
    if feature_importance:
        lines.extend([
            "",
            "## 7. 特征解释与目标关系",
            "",
            "### 7.1 特征重要性/相关性排名",
            "",
            f"- 特征排名来源：{'模型给出的特征重要性' if using_artifact_importance else 'CSV 中特征与目标列的统计关系'}。",
            "",
            *_feature_importance_table_lines(feature_importance),
        ])
    else:
        lines.extend([
            "",
            "## 7. 特征解释与目标关系",
            "",
            "- 当前没有可量化的特征重要性或统计相关性结果。",
        ])
    if relationship_notes:
        lines.extend([
            "",
            "### 7.2 特征与目标关系解读",
            "",
            *[f"- {item}" for item in relationship_notes[:12]],
        ])
    lines.extend([
        "",
        "## 8. 风险和局限",
        "",
        *[f"- {item}" for item in limitation_notes],
        "",
        "## 9. 结论",
        "",
        *_conclusion_lines(task, agent_loop, feature_importance),
        "",
        "## 10. 下一步建议",
        "",
        *_next_step_lines(task, feature_importance),
    ])
    markdown = "\n".join(lines)
    _persist_report_markdown(task, markdown)
    return markdown


def _ensure_agent_loop_for_report(task: TaskRecord) -> None:
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    if isinstance(requirements.get("agent_loop"), dict):
        return
    if task.last_run:
        refresh_agent_loop_after_run(task)
    else:
        refresh_agent_loop_after_analysis(task)


def _build_target_profile(task: TaskRecord, profile: DatasetProfile | None) -> dict[str, Any]:
    target_column = task.label_column or (profile.target_column if profile else None)
    result: dict[str, Any] = {"status": "unavailable", "target_column": target_column}
    if not target_column:
        result["detail"] = "尚未确认目标列。"
        return result

    values: list[str] = []
    scanned_rows = 0
    if task.dataset_path:
        dataset_path = Path(task.dataset_path)
        if dataset_path.exists() and dataset_path.is_file():
            try:
                with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                    reader = csv.DictReader(handle)
                    if not reader.fieldnames or target_column not in reader.fieldnames:
                        result["detail"] = f"CSV 表头中没有找到目标列 {target_column}。"
                        return result
                    for index, row in enumerate(reader):
                        if index >= MAX_TARGET_PROFILE_ROWS:
                            break
                        scanned_rows += 1
                        value = _clean_cell(row.get(target_column))
                        if value:
                            values.append(value)
            except (OSError, csv.Error, UnicodeError) as exc:
                result["detail"] = f"读取目标列失败：{exc}"
                return result

    if not values and profile is not None and profile.preview_rows:
        for row in profile.preview_rows:
            value = _clean_cell(row.get(target_column))
            if value:
                values.append(value)
        scanned_rows = len(profile.preview_rows)
        result["source"] = "dataset_preview"
    else:
        result["source"] = "dataset_file"

    if not values:
        result["detail"] = "目标列没有可分析的非空值。"
        result["scanned_rows"] = scanned_rows
        return result

    numeric_values = [_to_float(value) for value in values]
    numeric_clean = [value for value in numeric_values if value is not None]
    result.update(
        {
            "status": "available",
            "count": len(values),
            "scanned_rows": scanned_rows,
            "distinct_count": len(set(values)),
        }
    )
    if len(numeric_clean) >= max(5, int(len(values) * 0.8)):
        result.update(
            {
                "kind": "numeric",
                "numeric_count": len(numeric_clean),
                "mean": sum(numeric_clean) / len(numeric_clean),
                "std": _sample_std(numeric_clean),
                "min": min(numeric_clean),
                "q1": _quantile(numeric_clean, 0.25),
                "median": _quantile(numeric_clean, 0.5),
                "q3": _quantile(numeric_clean, 0.75),
                "max": max(numeric_clean),
            }
        )
        return result

    distribution = Counter(values)
    total = sum(distribution.values()) or 1
    result.update(
        {
            "kind": "categorical",
            "class_count": len(distribution),
            "top_values": [
                {"value": label, "count": count, "ratio": count / total}
                for label, count in distribution.most_common(10)
            ],
        }
    )
    return result


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _quantile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _primary_metric_text(task: TaskRecord) -> str:
    if task.last_run:
        return f"{task.last_run.metric_name} = {_format_metric_value(task.last_run.metric_value)}"
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    metric_name = requirements.get("metric_name")
    return str(metric_name) if metric_name else "未记录"


def _report_scope_text(using_artifact_importance: bool) -> str:
    if using_artifact_importance:
        return "真实结果文件、候选模型对比、模型给出的特征重要性、简单对照与结果检查"
    return "真实结果文件、候选模型对比、简单对照、结果检查，以及 CSV 中特征与目标列的统计关系"


def _abstract_lines(
    task: TaskRecord,
    profile: DatasetProfile | None,
    agent_loop: dict[str, Any],
    feature_importance: list[FeatureImportanceEntry],
    candidate_count: int,
) -> list[str]:
    dataset_text = (
        f"数据集包含 {_format_integer(profile.row_count)} 行、{_format_integer(profile.column_count)} 列"
        if profile is not None
        else "当前没有可读取的数据集画像"
    )
    target_text = f"目标列为 `{task.label_column}`" if task.label_column else "目标列尚未确认"
    task_text = f"任务类型为 {task.problem_type}" if task.problem_type else "任务类型尚未确认"
    lines = [
        f"本报告围绕任务“{task.name}”整理自动建模全过程。{dataset_text}，{target_text}，{task_text}。",
    ]
    baseline = agent_loop.get("baseline") if isinstance(agent_loop, dict) else None
    if isinstance(baseline, dict) and baseline.get("status") == "completed":
        lines.append(
            "系统首先建立简单对照："
            f"{baseline.get('label') or baseline.get('method') or '简单对照'}，"
            f"{baseline.get('metric_name')} = {_format_metric_value(baseline.get('metric_value'))}。"
        )
    elif isinstance(baseline, dict):
        lines.append(f"简单对照当前未完成：{baseline.get('detail') or baseline.get('status') or '暂无细节'}。")
    else:
        lines.append("当前任务没有记录简单对照，因此报告无法给出最低参考线结论。")

    if task.last_run:
        comparison = _compare_task_to_baseline(task, baseline)
        comparison_text = f"；{_comparison_sentence(comparison)}" if comparison else ""
        lines.append(
            f"自动建模阶段共解析到 {_format_integer(candidate_count)} 个候选模型，"
            f"当前最优模型为 {task.last_run.best_model}，"
            f"{task.last_run.metric_name} = {_format_metric_value(task.last_run.metric_value)}{comparison_text}。"
        )
    else:
        lines.append("自动建模阶段尚未产出成功模型，本报告只能作为数据诊断和过程复盘，不能作为最终模型验收。")

    if feature_importance:
        lines.append(f"解释性分析中，排名靠前的特征包括：{_format_top_features(feature_importance)}。")
    else:
        lines.append("当前没有可用的特征重要性或稳定相关性结果，解释性部分需要在后续运行中补齐。")
    return lines


def _task_background_lines(
    task: TaskRecord,
    profile: DatasetProfile | None,
    target_profile: dict[str, Any],
) -> list[str]:
    rows = [
        f"- 业务描述：{task.description or '未填写'}",
        f"- 建模目标：使用 CSV 中的特征字段预测 `{task.label_column or '未确认目标列'}`。",
        f"- 问题类型：{task.problem_type or '未解析'}。",
        f"- 评价指标：{_primary_metric_text(task)}。",
        "- 交付内容：数据质量检查、简单对照、自动建模结果、候选模型比较、结果检查、优化复盘和下一步建议。",
    ]
    if profile is not None:
        rows.append(f"- 数据规模：{_format_integer(profile.row_count)} 行、{_format_integer(profile.column_count)} 列。")
    if target_profile.get("status") == "available":
        rows.append(
            f"- 目标列画像：非空样本 {_format_integer(target_profile.get('count'))}，"
            f"不同取值 {_format_integer(target_profile.get('distinct_count'))}。"
        )
    return rows


def _dataset_overview_lines(profile: DatasetProfile | None, target_profile: dict[str, Any]) -> list[str]:
    if profile is None:
        return ["- 当前没有可读取的数据集画像。"]
    lines = [
        "| 项目 | 数值 |",
        "| --- | --- |",
        f"| 文件名 | {_escape_table_cell(profile.filename or '未记录')} |",
        f"| 样本行数 | {_format_integer(profile.row_count)} |",
        f"| 字段数 | {_format_integer(profile.column_count)} |",
        f"| 目标列 | {_escape_table_cell(profile.target_column or '未记录')} |",
        f"| 画像生成时间 | {_escape_table_cell(profile.generated_at.isoformat())} |",
        "",
        "目标列统计如下。",
        "",
    ]
    if target_profile.get("status") != "available":
        lines.append(f"- {target_profile.get('detail') or '目标列统计不可用。'}")
        return lines
    if target_profile.get("kind") == "numeric":
        lines.extend(
            [
                "| 统计量 | 数值 |",
                "| --- | ---: |",
                f"| 非空样本数 | {_format_integer(target_profile.get('count'))} |",
                f"| 均值 | {_format_metric_value(target_profile.get('mean'))} |",
                f"| 标准差 | {_format_metric_value(target_profile.get('std'))} |",
                f"| 最小值 | {_format_metric_value(target_profile.get('min'))} |",
                f"| 25% 分位数 | {_format_metric_value(target_profile.get('q1'))} |",
                f"| 中位数 | {_format_metric_value(target_profile.get('median'))} |",
                f"| 75% 分位数 | {_format_metric_value(target_profile.get('q3'))} |",
                f"| 最大值 | {_format_metric_value(target_profile.get('max'))} |",
            ]
        )
        return lines
    lines.extend(
        [
            f"- 目标列共有 {_format_integer(target_profile.get('class_count'))} 个不同取值；下表展示出现次数最多的类别。",
            "",
            "| 类别 | 数量 | 占比 |",
            "| --- | ---: | ---: |",
        ]
    )
    for item in target_profile.get("top_values") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {_escape_table_cell(item.get('value'))} | {_format_integer(item.get('count'))} | {_format_percent(item.get('ratio'))} |"
        )
    return lines


def _field_quality_table_lines(profile: DatasetProfile | None) -> list[str]:
    if profile is None:
        return ["- 当前没有字段画像，无法输出字段级质量表。"]
    lines = [
        "| 字段 | 推断类型 | 非空数 | 缺失数 | 缺失率 | 示例值 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for column in profile.columns[:30]:
        sample_values = "、".join(column.sample_values[:3]) if column.sample_values else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table_cell(column.name),
                    _escape_table_cell(column.inferred_type),
                    _format_integer(column.non_empty_count),
                    _format_integer(column.missing_count),
                    _format_percent(column.missing_ratio),
                    _escape_table_cell(sample_values or "无"),
                ]
            )
            + " |"
        )
    if len(profile.columns) > 30:
        lines.append(f"- 字段数量较多，表格仅展示前 30 个字段；完整字段数为 {_format_integer(len(profile.columns))}。")
    return lines


def _workflow_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    workflow = agent_loop.get("workflow") if isinstance(agent_loop, dict) else None
    if not isinstance(workflow, list) or not workflow:
        return ["- 尚未记录自动建模执行流程。"]
    lines = [
        "| 阶段 | 状态 | 说明 |",
        "| --- | --- | --- |",
    ]
    for step in workflow:
        if not isinstance(step, dict):
            continue
        lines.append(
            f"| {_escape_table_cell(step.get('label') or step.get('key') or '阶段')} "
            f"| {_escape_table_cell(_status_label(step.get('status')))} "
            f"| {_escape_table_cell(step.get('detail') or '')} |"
        )
    return lines


def _checklist_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    checklist = agent_loop.get("checklist") if isinstance(agent_loop, dict) else None
    if not isinstance(checklist, list) or not checklist:
        return ["- 尚未记录任务检查清单。"]
    lines = [
        "| 检查项 | 状态 | 证据/说明 |",
        "| --- | --- | --- |",
    ]
    for item in checklist:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {_escape_table_cell(item.get('title') or item.get('id') or '检查项')} "
            f"| {_escape_table_cell(_status_label(item.get('status')))} "
            f"| {_escape_table_cell(item.get('detail') or '')} |"
        )
    return lines


def _baseline_experiment_lines(agent_loop: dict[str, Any], task: TaskRecord) -> list[str]:
    baseline = agent_loop.get("baseline") if isinstance(agent_loop, dict) else None
    if not isinstance(baseline, dict):
        return ["- 尚未记录简单对照，无法和正式模型做最低参考线对比。"]
    if baseline.get("status") != "completed":
        return [f"- 简单对照状态：{_status_label(baseline.get('status'))}。{baseline.get('detail') or '尚无细节。'}"]

    lines = [
        "简单对照的作用是先用最简单、可解释的方法建立最低参考线，确认自动模型确实学到了超过常数预测或多数类预测的信息。",
        "",
        "| 项目 | 数值 |",
        "| --- | --- |",
        f"| 方法 | {_escape_table_cell(baseline.get('label') or baseline.get('method') or '简单对照')} |",
        f"| 问题类型 | {_escape_table_cell(baseline.get('problem_type') or task.problem_type or '未记录')} |",
        f"| 目标列 | {_escape_table_cell(baseline.get('target_column') or task.label_column or '未记录')} |",
        f"| 训练样本数 | {_format_integer(baseline.get('train_count'))} |",
        f"| 验证样本数 | {_format_integer(baseline.get('validation_count'))} |",
        f"| 评价指标 | {_escape_table_cell(baseline.get('metric_name') or 'metric')} |",
        f"| 指标数值 | {_format_metric_value(baseline.get('metric_value'))} |",
    ]
    if baseline.get("prediction_value") is not None:
        lines.append(f"| 常数预测值 | {_format_metric_value(baseline.get('prediction_value'))} |")
    if baseline.get("majority_label") is not None:
        lines.append(f"| 多数类 | {_escape_table_cell(baseline.get('majority_label'))} |")
        lines.append(f"| 多数类训练占比 | {_format_percent(baseline.get('majority_ratio'))} |")
    distribution = baseline.get("class_distribution")
    if isinstance(distribution, dict) and distribution:
        lines.extend(["", "多数类简单对照的训练集类别分布如下。", "", "| 类别 | 数量 |", "| --- | ---: |"])
        for label, count in list(distribution.items())[:10]:
            lines.append(f"| {_escape_table_cell(label)} | {_format_integer(count)} |")
    notes = baseline.get("notes")
    if isinstance(notes, list) and notes:
        lines.extend(["", "简单对照说明："])
        lines.extend([f"- {item}" for item in notes if isinstance(item, str)])

    comparison = _compare_task_to_baseline(task, baseline)
    if comparison:
        lines.extend(["", f"正式模型对比：{_comparison_sentence(comparison)}"])
    elif task.last_run:
        lines.extend(["", "- 正式模型与简单对照的指标口径不一致或简单对照不完整，暂不能直接比较。"])
    return lines


def _artifact_report_lines(artifact_index: Any) -> list[str]:
    lines = [
        "| 文件 | 状态 | 路径 |",
        "| --- | --- | --- |",
        f"| 输出目录 | {_artifact_status(artifact_index.output_dir)} | {_escape_table_cell(_path_text(artifact_index.output_dir))} |",
        f"| 结果摘要 | {_artifact_status(artifact_index.run_summary_path)} | {_escape_table_cell(_path_text(artifact_index.run_summary_path))} |",
        f"| 候选模型对比 | {_artifact_status(artifact_index.leaderboard_path)} | {_escape_table_cell(_path_text(artifact_index.leaderboard_path))} |",
        f"| AI 使用记录 | {_artifact_status(artifact_index.token_usage_path)} | {_escape_table_cell(_path_text(artifact_index.token_usage_path))} |",
        f"| 生成代码 | {_artifact_status(artifact_index.generated_code_path)} | {_escape_table_cell(_path_text(artifact_index.generated_code_path))} |",
        f"| 可加载模型 | {_artifact_status(artifact_index.predictor_dir)} | {_escape_table_cell(_path_text(artifact_index.predictor_dir))} |",
    ]
    if artifact_index.feature_importance_paths:
        for index, path in enumerate(artifact_index.feature_importance_paths[:5], start=1):
            lines.append(f"| 特征重要性 {index} | 已找到 | {_escape_table_cell(str(path))} |")
    else:
        lines.append("| 特征重要性 | 未找到 | 未记录 |")
    return lines


def _stop_condition_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    stop_conditions = agent_loop.get("stop_conditions") if isinstance(agent_loop, dict) else None
    if not isinstance(stop_conditions, dict) or not stop_conditions:
        return ["- 尚未记录停止条件。"]
    return [
        "| 条件 | 当前值 |",
        "| --- | --- |",
        f"| 最大模型尝试次数 | {_format_integer(stop_conditions.get('max_attempts'))} |",
        f"| 最小相对改善阈值 | {_format_percent(stop_conditions.get('min_relative_improvement'))} |",
        f"| 最大连续失败/无效尝试 | {_format_integer(stop_conditions.get('max_consecutive_failed_or_unhelpful_attempts'))} |",
        f"| 当前模型尝试次数 | {_format_integer(stop_conditions.get('current_model_attempts'))} |",
        f"| 最近失败/无效尝试次数 | {_format_integer(stop_conditions.get('recent_failed_or_unhelpful_attempts'))} |",
        f"| 是否建议停止 | {'是' if stop_conditions.get('should_stop') else '否'} |",
    ]


def _feature_importance_table_lines(feature_importance: list[FeatureImportanceEntry]) -> list[str]:
    lines = [
        "| 排名 | 特征 | 分数 | 来源 |",
        "| ---: | --- | ---: | --- |",
    ]
    for index, item in enumerate(feature_importance[:15], start=1):
        lines.append(
            f"| {index} | {_escape_table_cell(item.feature)} | {_format_metric_value(item.importance)} | {_escape_table_cell(item.source or 'unknown')} |"
        )
    return lines


def _conclusion_lines(
    task: TaskRecord,
    agent_loop: dict[str, Any],
    feature_importance: list[FeatureImportanceEntry],
) -> list[str]:
    if not task.last_run:
        return [
            "1. 当前任务还没有成功模型结果，不能给出最终模型优劣结论。",
            "2. 已有数据画像、简单对照或失败诊断仍可作为下一轮修复依据。",
            "3. 后续应先补齐结果摘要、候选模型对比和 AI 使用记录，再生成最终验收报告。",
        ]
    baseline = agent_loop.get("baseline") if isinstance(agent_loop, dict) else None
    comparison = _compare_task_to_baseline(task, baseline)
    lines = [
        f"1. 本次自动建模已完成，最佳模型为 {task.last_run.best_model}，{task.last_run.metric_name} = {_format_metric_value(task.last_run.metric_value)}。",
    ]
    if comparison:
        lines.append(f"2. 与简单对照相比，{_comparison_sentence(comparison)}")
    else:
        lines.append("2. 当前无法和简单对照做同口径比较，模型验收时应先补齐或确认简单对照指标。")
    if feature_importance:
        lines.append(f"3. 从解释性结果看，{_format_top_features(feature_importance, limit=3)} 是当前最值得复核的关键字段。")
    else:
        lines.append("3. 当前解释性证据不足，建议补充模型原生特征重要性后再做业务验收。")
    raw_gates = agent_loop.get("quality_gates") if isinstance(agent_loop, dict) else []
    gates = raw_gates if isinstance(raw_gates, list) else []
    warnings = [gate for gate in gates if isinstance(gate, dict) and gate.get("status") in {"warning", "blocked"}]
    if warnings:
        lines.append(f"4. 仍有 {len(warnings)} 个结果检查问题需要处理，最优先项为：{warnings[0].get('title') or warnings[0].get('id')}。")
    else:
        lines.append("4. 当前没有记录阻塞级检查问题，可以进入人工复核和业务验收。")
    return lines


def _compare_task_to_baseline(task: TaskRecord, baseline: Any) -> dict[str, Any] | None:
    if not task.last_run or not isinstance(baseline, dict) or baseline.get("status") != "completed":
        return None
    model_metric = _normalize_report_metric(task.last_run.metric_name)
    baseline_metric = _normalize_report_metric(str(baseline.get("metric_name") or ""))
    if model_metric != baseline_metric:
        return None
    baseline_value = _coerce_float(baseline.get("metric_value"))
    model_value = _coerce_float(task.last_run.metric_value)
    if baseline_value is None or model_value is None:
        return None
    lower_better = model_metric in REPORT_LOWER_IS_BETTER_METRICS
    if lower_better:
        delta = baseline_value - model_value
    else:
        delta = model_value - baseline_value
    denominator = abs(baseline_value) if abs(baseline_value) > 1e-12 else 1.0
    return {
        "metric_name": task.last_run.metric_name,
        "model_value": model_value,
        "baseline_value": baseline_value,
        "delta": delta,
        "relative_delta": delta / denominator,
        "better": delta > 0,
        "direction": "lower" if lower_better else "higher",
    }


def _comparison_sentence(comparison: dict[str, Any]) -> str:
    direction = "降低" if comparison.get("direction") == "lower" else "提高"
    if not comparison.get("better"):
        direction = "未改善"
    return (
        f"模型 {comparison.get('metric_name')} = {_format_metric_value(comparison.get('model_value'))}，"
        f"简单对照 = {_format_metric_value(comparison.get('baseline_value'))}，"
        f"相对简单对照{direction} {_format_percent(abs(comparison.get('relative_delta') or 0))}"
    )


def _normalize_report_metric(metric_name: str | None) -> str:
    return str(metric_name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _format_metric_value(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "暂无"
    return f"{numeric:.6g}"


def _format_integer(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "暂无"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _format_percent(value: Any) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "暂无"
    return f"{numeric:.1%}"


def _escape_table_cell(value: Any) -> str:
    text = "暂无" if value is None or value == "" else str(value)
    return text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")


def _status_label(status: Any) -> str:
    mapping = {
        "completed": "已完成",
        "passed": "通过",
        "accepted": "已采纳",
        "blocked": "阻塞",
        "failed": "失败",
        "warning": "需确认",
        "pending": "等待中",
        "running": "运行中",
        "proposed": "建议调优",
        "needs_improvement": "需要改进",
    }
    return mapping.get(str(status or ""), str(status or "未知"))


def _artifact_status(path: Any) -> str:
    return "已找到" if path else "未找到"


def _path_text(path: Any) -> str:
    return str(path) if path else "未记录"


def _agent_loop(task: TaskRecord) -> dict[str, Any]:
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    loop = requirements.get("agent_loop")
    return dict(loop) if isinstance(loop, dict) else {}


def _baseline_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    baseline = agent_loop.get("baseline")
    if not isinstance(baseline, dict):
        return ["- 尚未记录简单对照。"]
    status = baseline.get("status")
    if status != "completed":
        detail = baseline.get("detail") or "简单对照尚未完成。"
        return [f"- 简单对照状态：{status or 'unknown'}，{detail}"]
    metric_name = baseline.get("metric_name") or "metric"
    metric_value = baseline.get("metric_value")
    method = baseline.get("label") or baseline.get("method") or "简单对照"
    sample_count = baseline.get("sample_count")
    value_text = f"{float(metric_value):.6g}" if isinstance(metric_value, (int, float)) else str(metric_value)
    lines = [
        f"- {method}：{metric_name} = {value_text}。",
    ]
    if sample_count is not None:
        lines.append(f"- 简单对照样本数：{sample_count}。")
    return lines


def _quality_gate_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    gates = agent_loop.get("quality_gates")
    if not isinstance(gates, list) or not gates:
        return ["- 尚未形成结果检查结论。"]
    lines = [
        "| 检查项 | 状态 | 结论 |",
        "| --- | --- | --- |",
    ]
    for gate in gates[:8]:
        if not isinstance(gate, dict):
            continue
        title = gate.get("title") or gate.get("id") or "质量检查"
        status = gate.get("status") or "unknown"
        detail = gate.get("detail") or ""
        lines.append(
            f"| {_escape_table_cell(title)} | {_escape_table_cell(_status_label(status))} | {_escape_table_cell(detail)} |"
        )
    return lines if len(lines) > 2 else ["- 尚未形成结果检查结论。"]


def _tuning_attempt_report_lines(agent_loop: dict[str, Any]) -> list[str]:
    attempts = agent_loop.get("tuning_attempts")
    if not isinstance(attempts, list) or not attempts:
        return ["- 尚未记录优化尝试。"]
    lines = [
        "| 轮次 | 类型 | 状态 | 假设 | 动作 | 指标变化 | 说明 |",
        "| ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for attempt in attempts[-8:]:
        if not isinstance(attempt, dict):
            continue
        index = attempt.get("attempt_index")
        kind = attempt.get("kind") or "attempt"
        status = attempt.get("status") or "unknown"
        hypothesis = attempt.get("hypothesis") or ""
        action = attempt.get("action") or ""
        notes = attempt.get("notes") or ""
        lines.append(
            "| "
            + " | ".join(
                [
                    _format_integer(index),
                    _escape_table_cell(kind),
                    _escape_table_cell(_status_label(status)),
                    _escape_table_cell(hypothesis),
                    _escape_table_cell(action),
                    _escape_table_cell(_attempt_metric_change(attempt)),
                    _escape_table_cell(notes),
                ]
            )
            + " |"
        )
    next_improvement = agent_loop.get("next_improvement")
    if isinstance(next_improvement, dict) and next_improvement.get("status") not in {None, "not_needed"}:
        lines.extend(["", f"- 下一步建议：{next_improvement.get('action') or next_improvement.get('detail')}"])
    return lines if len(lines) > 2 else ["- 尚未记录优化尝试。"]


def _format_top_features(feature_importance: list[FeatureImportanceEntry], *, limit: int = 5) -> str:
    return "、".join(f"{item.feature}({item.importance:.3g})" for item in feature_importance[:limit])


def _attempt_metric_change(attempt: dict[str, Any]) -> str:
    before = attempt.get("metric_before")
    after = attempt.get("metric_after")
    before_text = _metric_snapshot_text(before)
    after_text = _metric_snapshot_text(after)
    if before_text and after_text:
        return f"{before_text} -> {after_text}"
    return after_text or before_text or "未记录"


def _metric_snapshot_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    metric_name = payload.get("metric_name")
    metric_value = payload.get("metric_value")
    if not metric_name and metric_value is None:
        return ""
    return f"{metric_name or 'metric'}={_format_metric_value(metric_value)}"


def _run_conclusion(task: TaskRecord) -> str:
    if task.last_run:
        return "已完成，可基于本报告做模型验收"
    if task.last_run_attempt and task.last_run_attempt.diagnosis:
        return f"未完成，最后一次运行诊断为：{task.last_run_attempt.diagnosis}"
    if task.status.value == "running":
        return "仍在运行或等待修复，当前报告不是最终成功验收报告"
    return "未完成，尚无成功模型结果"


def _model_result_lines(task: TaskRecord) -> list[str]:
    if not task.last_run:
        attempt = task.last_run_attempt
        lines = ["- 暂无成功模型结果。"]
        if attempt is not None:
            lines.append(f"- 最近运行目录：{attempt.output_dir}。")
            if attempt.diagnosis_detail:
                lines.append(f"- 最近诊断：{attempt.diagnosis_detail}")
        return lines
    lines = [
        f"- 最佳模型：{task.last_run.best_model}",
        f"- 评价指标：{task.last_run.metric_name}",
        f"- 指标数值：{_format_metric_value(task.last_run.metric_value)}",
    ]
    if task.last_run.validation_score is not None:
        lines.append(f"- 候选排序分：{_format_metric_value(task.last_run.validation_score)}")
    if task.last_run.leaderboard:
        lines.extend(
            [
                "",
                "| 排名 | 模型 | validation_score | metric_value | fit_time | pred_time |",
                "| ---: | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for index, row in enumerate(task.last_run.leaderboard[:8], start=1):
            model = row.get("model") or row.get("name") or row.get("model_name") or "unknown"
            score = row.get("validation_score", row.get("score_val"))
            metric_value = row.get("metric_value")
            fit_time = row.get("fit_time")
            pred_time = row.get("pred_time")
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(index),
                        _escape_table_cell(model),
                        _format_metric_value(score),
                        _format_metric_value(metric_value),
                        _format_metric_value(fit_time),
                        _format_metric_value(pred_time),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- 当前没有解析到候选模型对比结果。")
    return lines


def _next_step_lines(task: TaskRecord, feature_importance: list[FeatureImportanceEntry]) -> list[str]:
    if not task.last_run:
        return [
            "- 先重新运行并拿到完整结果摘要、候选模型对比和 AI 使用记录，再做模型验收。",
            "- 如果运行中断，优先处理运行日志中的具体异常，而不是只看候选模型分数。",
        ]
    lines = [
        "- 用独立验证集或时间外样本复核当前指标，避免只相信一次自动划分结果。",
        "- 对排名靠前的特征做业务复核，确认它们不是泄漏字段、文件路径、ID 或事后字段。",
    ]
    if not feature_importance:
        lines.append("- 补充模型给出的特征重要性，增强解释性。")
    return lines


def _persist_report_markdown(task: TaskRecord, markdown: str) -> None:
    output_dir = None
    if task.last_run and task.last_run.output_dir:
        output_dir = Path(task.last_run.output_dir)
    elif task.last_run_attempt and task.last_run_attempt.output_dir:
        output_dir = Path(task.last_run_attempt.output_dir)
    if output_dir is None or not output_dir.exists():
        return
    try:
        (output_dir / "final_report.md").write_text(markdown, encoding="utf-8")
    except OSError:
        return


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
