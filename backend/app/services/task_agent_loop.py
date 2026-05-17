from __future__ import annotations

import csv
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetProfile, TaskRecord, TaskStatus


MAX_BASELINE_ROWS = 50_000
MAX_PREVIEW_DISTINCT_VALUES = 200
LOWER_IS_BETTER_METRICS = {
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
CLASSIFICATION_METRICS = {"accuracy", "balanced_accuracy", "f1"}
REGRESSION_METRICS = {"rmse", "root_mean_squared_error", "mse", "mean_squared_error", "mae", "mean_absolute_error", "r2"}


def initialize_agent_loop_for_upload(task: TaskRecord) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    loop["checklist"] = _build_checklist(task)
    loop["baseline"] = _baseline_pending("等待 AI 或人工确认目标列和问题类型后计算简单对照。")
    loop["quality_gates"] = _build_quality_gates(task, loop["baseline"])
    loop["tuning_attempts"] = _normalize_attempts(loop.get("tuning_attempts"))
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def refresh_agent_loop_after_analysis(task: TaskRecord) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    loop["checklist"] = _build_checklist(task)
    loop["baseline"] = _compute_baseline(task)
    loop["quality_gates"] = _build_quality_gates(task, loop["baseline"])
    loop["tuning_attempts"] = _merge_baseline_attempt(_normalize_attempts(loop.get("tuning_attempts")), loop["baseline"])
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def refresh_agent_loop_after_run(task: TaskRecord) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    baseline = loop.get("baseline")
    if not _baseline_completed(baseline):
        baseline = _compute_baseline(task)
    loop["checklist"] = _build_checklist(task)
    loop["baseline"] = baseline
    attempts = _merge_baseline_attempt(_normalize_attempts(loop.get("tuning_attempts")), baseline)
    attempts = _merge_run_attempt(attempts, task, baseline)
    loop["tuning_attempts"] = _merge_improvement_suggestion(attempts, task, baseline)
    loop["quality_gates"] = _build_quality_gates(task, baseline)
    loop["next_improvement"] = _build_next_improvement(task, baseline, loop["quality_gates"], loop["tuning_attempts"])
    loop["stop_conditions"] = _build_stop_conditions(loop["tuning_attempts"])
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def refresh_agent_loop_after_run_failure(
    task: TaskRecord,
    *,
    error_summary: str | None = None,
    output_dir: str | None = None,
) -> TaskRecord:
    requirements = _requirements(task)
    loop = _base_loop(task)
    baseline = loop.get("baseline")
    if not _baseline_completed(baseline):
        baseline = _compute_baseline(task)
    attempts = _merge_baseline_attempt(_normalize_attempts(loop.get("tuning_attempts")), baseline)
    failure_key = f"run_failure:{output_dir or task.updated_at.isoformat()}"
    if not any(item.get("correlation_key") == failure_key for item in attempts):
        attempts.append(
            {
                "attempt_index": len(attempts),
                "correlation_key": failure_key,
                "kind": "run_failure",
                "hypothesis": "自动建模遇到可恢复或失败路径，需要根据日志修复后再继续。",
                "action": "保留失败文件和诊断信息，等待重新运行或人工复核。",
                "changed_config": {},
                "metric_before": _metric_snapshot(baseline),
                "metric_after": None,
                "accepted": False,
                "status": "failed",
                "output_dir": output_dir,
                "notes": error_summary or task.notes or "本次运行未产出成功模型。",
                "created_at": _now_iso(),
            }
        )
    loop["baseline"] = baseline
    loop["checklist"] = _build_checklist(task)
    loop["tuning_attempts"] = attempts[-20:]
    loop["quality_gates"] = _build_quality_gates(task, baseline, failure_note=error_summary)
    loop["next_improvement"] = _build_next_improvement(task, baseline, loop["quality_gates"], loop["tuning_attempts"])
    loop["stop_conditions"] = _build_stop_conditions(loop["tuning_attempts"])
    loop["workflow"] = _build_workflow(task, loop)
    requirements["agent_loop"] = _stamp_loop(loop)
    task.structured_requirements = requirements
    return task


def _requirements(task: TaskRecord) -> dict[str, Any]:
    return dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}


def _base_loop(task: TaskRecord) -> dict[str, Any]:
    existing = _requirements(task).get("agent_loop")
    loop = dict(existing) if isinstance(existing, dict) else {}
    loop.setdefault("version", 1)
    loop.setdefault("tuning_attempts", [])
    loop.setdefault("stop_conditions", _build_stop_conditions(loop.get("tuning_attempts")))
    loop["task_id"] = task.id
    return loop


def _stamp_loop(loop: dict[str, Any]) -> dict[str, Any]:
    loop["version"] = 1
    loop["updated_at"] = _now_iso()
    return loop


def _build_checklist(task: TaskRecord) -> list[dict[str, Any]]:
    profile = _profile(task)
    metric_name = _metric_name(task)
    items = [
        _check_item(
            "dataset_uploaded",
            "CSV 数据已上传",
            "passed" if task.dataset_path else "blocked",
            f"数据文件：{task.dataset_filename or '未上传'}",
            task.dataset_path,
        ),
        _check_item(
            "dataset_profile",
            "数据画像已生成",
            "passed" if profile and profile.column_count > 0 else "blocked",
            _profile_summary(profile),
            "dataset_profile",
        ),
        _check_item(
            "target_column",
            "预测目标已确认",
            "passed" if task.label_column else "pending",
            f"目标列：{task.label_column or '等待 AI 或人工确认'}",
            task.label_column,
        ),
        _check_item(
            "problem_type",
            "问题类型已确认",
            "passed" if task.problem_type in {"classification", "regression"} else "pending",
            f"问题类型：{task.problem_type or '等待确认'}",
            task.problem_type,
        ),
        _check_item(
            "metric_name",
            "评价指标已确认",
            "passed" if metric_name else "pending",
            f"指标：{metric_name or '等待确认'}",
            metric_name,
        ),
    ]
    if profile and task.label_column and task.label_column not in [column.name for column in profile.columns]:
        items.append(
            _check_item(
                "target_in_columns",
                "目标列存在于 CSV 表头",
                "blocked",
                f"目标列 {task.label_column} 不在当前 CSV 表头中。",
                task.label_column,
            )
        )
    elif task.label_column:
        items.append(
            _check_item(
                "target_in_columns",
                "目标列存在于 CSV 表头",
                "passed",
                f"已在 CSV 中找到目标列 {task.label_column}。",
                task.label_column,
            )
        )
    if profile:
        missing_warnings = [
            column for column in profile.columns if column.missing_ratio >= 0.3
        ]
        items.append(
            _check_item(
                "missing_values",
                "缺失值风险检查",
                "warning" if missing_warnings else "passed",
                "高缺失字段：" + "、".join(f"{item.name}({item.missing_ratio:.0%})" for item in missing_warnings[:5])
                if missing_warnings
                else "未发现缺失比例超过 30% 的字段。",
                "dataset_profile.columns",
            )
        )
        if profile.row_count < 30:
            leakage_status = "warning"
            leakage_detail = "样本量较少，模型验证结果可能不稳定。"
        else:
            leakage_status = "passed"
            leakage_detail = "样本量达到轻量验证的最低要求。"
        items.append(_check_item("sample_size", "样本量检查", leakage_status, leakage_detail, profile.row_count))
    return items


def _check_item(item_id: str, title: str, status: str, detail: str, evidence: Any = None) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": title,
        "status": status,
        "detail": detail,
        "evidence": evidence,
    }


def _profile(task: TaskRecord) -> DatasetProfile | None:
    return task.dataset_profile


def _profile_summary(profile: DatasetProfile | None) -> str:
    if profile is None:
        return "尚未生成数据画像。"
    return f"{profile.row_count} 行，{profile.column_count} 列。"


def _compute_baseline(task: TaskRecord) -> dict[str, Any]:
    if not task.dataset_path or not task.label_column or task.problem_type not in {"classification", "regression"}:
        return _baseline_pending("等待数据集、目标列和问题类型齐备后计算简单对照。")
    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists() or not dataset_path.is_file():
        return _baseline_blocked(f"数据集文件不存在，无法计算简单对照：{dataset_path}")
    try:
        rows = _read_target_rows(dataset_path, task.label_column)
    except (OSError, csv.Error, UnicodeError) as exc:
        return _baseline_blocked(f"读取 CSV 失败，无法计算简单对照：{exc}")
    if len(rows) < 5:
        return _baseline_blocked("可用于基线验证的目标值少于 5 行。")
    metric_name = _baseline_metric_name(task)
    if task.problem_type == "regression":
        return _compute_regression_baseline(task, rows, metric_name)
    return _compute_classification_baseline(task, rows, metric_name)


def _read_target_rows(dataset_path: Path, target_column: str) -> list[str]:
    rows: list[str] = []
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or target_column not in reader.fieldnames:
            return []
        for index, row in enumerate(reader):
            if index >= MAX_BASELINE_ROWS:
                break
            value = row.get(target_column)
            if value is not None and str(value).strip() != "":
                rows.append(str(value).strip())
    return rows


def _compute_regression_baseline(task: TaskRecord, raw_values: list[str], metric_name: str) -> dict[str, Any]:
    numeric_values: list[float] = []
    for value in raw_values:
        try:
            numeric = float(value)
        except ValueError:
            continue
        if math.isfinite(numeric):
            numeric_values.append(numeric)
    if len(numeric_values) < 5:
        return _baseline_blocked("目标列无法稳定转换为数值，不能计算回归简单对照。")
    train, validation = _deterministic_split(numeric_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    prediction = sum(train) / len(train)
    errors = [value - prediction for value in validation]
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mae = sum(abs(error) for error in errors) / len(errors)
    mse = sum(error * error for error in errors) / len(errors)
    metric_key = _normalize_metric(metric_name)
    if metric_key in {"mae", "mean_absolute_error"}:
        metric_value = mae
        resolved_metric = "mae"
    elif metric_key in {"mse", "mean_squared_error"}:
        metric_value = mse
        resolved_metric = "mse"
    elif metric_key == "r2":
        mean_validation = sum(validation) / len(validation)
        total_ss = sum((value - mean_validation) ** 2 for value in validation)
        residual_ss = sum(error * error for error in errors)
        metric_value = 1 - residual_ss / total_ss if total_ss > 0 else 0.0
        resolved_metric = "r2"
    else:
        metric_value = rmse
        resolved_metric = "rmse"
    return {
        "status": "completed",
        "method": "mean_target_baseline",
        "label": "均值预测基线",
        "problem_type": "regression",
        "target_column": task.label_column,
        "requested_metric_name": metric_name,
        "metric_name": resolved_metric,
        "metric_value": metric_value,
        "validation_score": _validation_score(resolved_metric, metric_value),
        "direction": "lower" if _is_lower_better(resolved_metric) else "higher",
        "sample_count": len(numeric_values),
        "train_count": len(train),
        "validation_count": len(validation),
        "prediction_value": prediction,
        "generated_at": _now_iso(),
        "notes": [
            "简单对照使用确定性 80/20 划分，仅用训练部分目标均值预测验证部分。",
            "后续模型至少应优于这个简单对照，否则需要进入优化或人工复核。",
        ],
    }


def _compute_classification_baseline(task: TaskRecord, raw_values: list[str], metric_name: str) -> dict[str, Any]:
    train, validation = _deterministic_split(raw_values)
    if not train or not validation:
        return _baseline_blocked("样本划分后训练集或验证集为空。")
    counts = Counter(train)
    majority_label, majority_count = counts.most_common(1)[0]
    predictions = [majority_label for _value in validation]
    accuracy = sum(1 for prediction, actual in zip(predictions, validation) if prediction == actual) / len(validation)
    labels = sorted(set(validation))
    recalls = []
    for label in labels:
        total = sum(1 for value in validation if value == label)
        correct = sum(1 for prediction, actual in zip(predictions, validation) if actual == label and prediction == actual)
        recalls.append(correct / total if total else 0.0)
    balanced_accuracy = sum(recalls) / len(recalls) if recalls else accuracy
    metric_key = _normalize_metric(metric_name)
    if metric_key == "balanced_accuracy":
        metric_value = balanced_accuracy
        resolved_metric = "balanced_accuracy"
    elif metric_key == "f1" and len(set(train)) == 2:
        positive = majority_label
        tp = sum(1 for prediction, actual in zip(predictions, validation) if prediction == positive and actual == positive)
        fp = sum(1 for prediction, actual in zip(predictions, validation) if prediction == positive and actual != positive)
        fn = sum(1 for prediction, actual in zip(predictions, validation) if prediction != positive and actual == positive)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        metric_value = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        resolved_metric = "f1"
    else:
        metric_value = accuracy
        resolved_metric = "accuracy"
    distribution = {
        str(label): count
        for label, count in counts.most_common(MAX_PREVIEW_DISTINCT_VALUES)
    }
    return {
        "status": "completed",
        "method": "majority_class_baseline",
        "label": "多数类预测基线",
        "problem_type": "classification",
        "target_column": task.label_column,
        "requested_metric_name": metric_name,
        "metric_name": resolved_metric,
        "metric_value": metric_value,
        "validation_score": _validation_score(resolved_metric, metric_value),
        "direction": "lower" if _is_lower_better(resolved_metric) else "higher",
        "sample_count": len(raw_values),
        "train_count": len(train),
        "validation_count": len(validation),
        "majority_label": majority_label,
        "majority_ratio": majority_count / len(train),
        "class_distribution": distribution,
        "generated_at": _now_iso(),
        "notes": [
            "简单对照使用确定性 80/20 划分，仅预测训练集中出现最多的类别。",
            "如果正式模型没有明显超过多数类简单对照，应检查类别不均衡、目标列和特征有效性。",
        ],
    }


def _deterministic_split(values: list[Any]) -> tuple[list[Any], list[Any]]:
    validation = [value for index, value in enumerate(values) if index % 5 == 0]
    train = [value for index, value in enumerate(values) if index % 5 != 0]
    if not validation and values:
        validation = values[-1:]
        train = values[:-1]
    return train, validation


def _baseline_pending(detail: str) -> dict[str, Any]:
    return {"status": "pending", "detail": detail, "generated_at": _now_iso()}


def _baseline_blocked(detail: str) -> dict[str, Any]:
    return {"status": "blocked", "detail": detail, "generated_at": _now_iso()}


def _baseline_completed(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") == "completed" and isinstance(value.get("metric_value"), (int, float))


def _baseline_metric_name(task: TaskRecord) -> str:
    metric_name = _metric_name(task)
    metric_key = _normalize_metric(metric_name)
    if task.problem_type == "regression":
        return metric_key if metric_key in REGRESSION_METRICS else "rmse"
    return metric_key if metric_key in CLASSIFICATION_METRICS else "accuracy"


def _metric_name(task: TaskRecord) -> str:
    requirements = _requirements(task)
    metric_name = requirements.get("metric_name")
    if isinstance(metric_name, str) and metric_name.strip():
        return metric_name.strip().lower()
    if task.last_run and task.last_run.metric_name:
        return task.last_run.metric_name
    return ""


def _build_quality_gates(
    task: TaskRecord,
    baseline: Any,
    *,
    failure_note: str | None = None,
) -> list[dict[str, Any]]:
    gates = [
        _gate(
            "semantic_ready",
            "任务语义可执行",
            "passed" if task.label_column and task.problem_type else "blocked",
            "目标列和问题类型已经确认。" if task.label_column and task.problem_type else "缺少目标列或问题类型。",
        ),
        _gate(
            "baseline_ready",
            "已建立简单对照",
            "passed" if _baseline_completed(baseline) else "warning" if isinstance(baseline, dict) and baseline.get("status") == "pending" else "blocked",
            baseline.get("detail") if isinstance(baseline, dict) and baseline.get("detail") else "简单对照已完成。",
        ),
    ]
    if failure_note:
        gates.append(_gate("run_failure", "运行失败诊断", "blocked", failure_note))
    if task.last_run:
        gates.append(
            _gate(
                "artifacts_complete",
                "真实结果文件完整",
                "passed" if task.last_run.leaderboard and task.last_run.token_usage else "warning",
                "已读取结果摘要、候选模型对比和 AI 使用记录。"
                if task.last_run.leaderboard and task.last_run.token_usage
                else "运行成功，但候选模型对比或 AI 使用记录不完整。",
            )
        )
        gates.append(_model_vs_baseline_gate(task, baseline))
        gates.append(
            _gate(
                "candidate_models",
                "候选模型数量",
                "passed" if len(task.last_run.leaderboard or []) >= 2 else "warning",
                f"当前解析到 {len(task.last_run.leaderboard or [])} 个候选模型。",
            )
        )
        suspicious = _suspicious_score_detail(task, baseline)
        if suspicious:
            gates.append(_gate("leakage_review", "疑似泄漏或异常高分检查", "warning", suspicious))
    elif task.status in {TaskStatus.failed, TaskStatus.running} and task.last_run_attempt:
        gates.append(
            _gate(
                "run_attempt",
                "最近一次运行状态",
                "warning" if task.status == TaskStatus.running else "blocked",
                task.last_run_attempt.diagnosis_detail or task.notes or "本次运行没有成功结果文件。",
            )
        )
    return gates


def _gate(gate_id: str, title: str, status: str, detail: str) -> dict[str, str]:
    return {"id": gate_id, "title": title, "status": status, "detail": detail}


def _model_vs_baseline_gate(task: TaskRecord, baseline: Any) -> dict[str, str]:
    if not task.last_run or not _baseline_completed(baseline):
        return _gate("model_vs_baseline", "模型优于简单对照", "warning", "缺少模型结果或简单对照，无法比较。")
    comparison = _compare_metric(
        task.last_run.metric_name,
        task.last_run.metric_value,
        str(baseline.get("metric_name") or ""),
        float(baseline.get("metric_value")),
    )
    if comparison is None:
        return _gate(
            "model_vs_baseline",
            "模型优于简单对照",
            "warning",
            f"模型指标 {task.last_run.metric_name} 与简单对照指标 {baseline.get('metric_name')} 不一致，无法直接比较。",
        )
    status = "passed" if comparison["better"] else "warning"
    return _gate(
        "model_vs_baseline",
        "模型优于简单对照",
        status,
        f"相对简单对照改善 {comparison['relative_delta']:.1%}。模型={comparison['model_value']:.6g}，简单对照={comparison['baseline_value']:.6g}。",
    )


def _suspicious_score_detail(task: TaskRecord, baseline: Any) -> str:
    if not task.last_run:
        return ""
    metric_key = _normalize_metric(task.last_run.metric_name)
    value = task.last_run.metric_value
    if metric_key in {"accuracy", "balanced_accuracy", "f1", "roc_auc", "auc"} and value >= 0.995:
        return "分类指标接近满分，建议人工确认是否存在目标泄漏、ID 泄漏或事后字段。"
    if _baseline_completed(baseline) and _normalize_metric(str(baseline.get("metric_name"))) == metric_key:
        comparison = _compare_metric(metric_key, value, metric_key, float(baseline["metric_value"]))
        if comparison and comparison["relative_delta"] >= 0.95:
            return "模型相对简单对照提升过大，建议检查数据划分和泄漏字段。"
    return ""


def _merge_baseline_attempt(attempts: list[dict[str, Any]], baseline: Any) -> list[dict[str, Any]]:
    if not _baseline_completed(baseline):
        return attempts
    if any(item.get("correlation_key") == "baseline" for item in attempts):
        return attempts
    attempts.append(
        {
            "attempt_index": len(attempts),
            "correlation_key": "baseline",
            "kind": "baseline",
            "hypothesis": "先用最简单、可解释的方法建立最低参考线。",
            "action": baseline.get("label") or baseline.get("method") or "简单对照",
            "changed_config": {"method": baseline.get("method")},
            "metric_before": None,
            "metric_after": _metric_snapshot(baseline),
            "accepted": True,
            "status": "completed",
            "notes": "简单对照已作为后续自动建模的比较对象。",
            "created_at": baseline.get("generated_at") or _now_iso(),
        }
    )
    return attempts


def _merge_run_attempt(attempts: list[dict[str, Any]], task: TaskRecord, baseline: Any) -> list[dict[str, Any]]:
    if not task.last_run:
        return attempts
    key = f"run:{task.last_run.output_dir}"
    if any(item.get("correlation_key") == key for item in attempts):
        return attempts
    comparison = None
    if _baseline_completed(baseline):
        comparison = _compare_metric(
            task.last_run.metric_name,
            task.last_run.metric_value,
            str(baseline.get("metric_name") or ""),
            float(baseline.get("metric_value")),
        )
    accepted = comparison["better"] if comparison else True
    attempts.append(
        {
            "attempt_index": len(attempts),
            "correlation_key": key,
            "kind": "model_run",
            "hypothesis": "使用自动建模搜索候选模型，期望超过简单对照。",
            "action": f"训练并比较 {len(task.last_run.leaderboard or [])} 个候选模型。",
            "changed_config": {
                "best_model": task.last_run.best_model,
                "metric_name": task.last_run.metric_name,
            },
            "metric_before": _metric_snapshot(baseline) if _baseline_completed(baseline) else None,
            "metric_after": {
                "metric_name": task.last_run.metric_name,
                "metric_value": task.last_run.metric_value,
                "validation_score": task.last_run.validation_score,
            },
            "accepted": bool(accepted),
            "status": "accepted" if accepted else "needs_improvement",
            "output_dir": task.last_run.output_dir,
            "notes": _run_attempt_note(comparison),
            "created_at": _now_iso(),
        }
    )
    return attempts[-20:]


def _merge_improvement_suggestion(
    attempts: list[dict[str, Any]],
    task: TaskRecord,
    baseline: Any,
) -> list[dict[str, Any]]:
    if not task.last_run:
        return attempts
    suggestion = _build_next_improvement(task, baseline, _build_quality_gates(task, baseline), attempts)
    if not suggestion or suggestion.get("status") == "not_needed":
        return attempts
    key = f"proposal:{task.last_run.output_dir}:{suggestion.get('reason_code')}"
    if any(item.get("correlation_key") == key for item in attempts):
        return attempts
    attempts.append(
        {
            "attempt_index": len(attempts),
            "correlation_key": key,
            "kind": "improvement_proposal",
            "hypothesis": suggestion.get("hypothesis"),
            "action": suggestion.get("action"),
            "changed_config": suggestion.get("changed_config") or {},
            "metric_before": {
                "metric_name": task.last_run.metric_name,
                "metric_value": task.last_run.metric_value,
                "validation_score": task.last_run.validation_score,
            },
            "metric_after": None,
            "accepted": False,
            "status": "proposed",
            "output_dir": task.last_run.output_dir,
            "notes": suggestion.get("detail"),
            "created_at": _now_iso(),
        }
    )
    return attempts[-20:]


def _build_next_improvement(
    task: TaskRecord,
    baseline: Any,
    quality_gates: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking = [gate for gate in quality_gates if gate.get("status") == "blocked"]
    warnings = [gate for gate in quality_gates if gate.get("status") == "warning"]
    if blocking:
        first = blocking[0]
        return {
            "status": "needs_human_or_retry",
            "reason_code": first.get("id"),
            "hypothesis": "阻塞项需要先被修复，否则继续自动调优没有意义。",
            "action": "处理阻塞项后从相关阶段重跑。",
            "detail": first.get("detail"),
            "changed_config": {"rerun_from_stage": "data_analysis"},
        }
    if task.last_run and any(gate.get("id") == "model_vs_baseline" and gate.get("status") == "warning" for gate in warnings):
        return {
            "status": "proposed",
            "reason_code": "model_vs_baseline",
            "hypothesis": "当前模型没有稳定超过简单对照，需要增加搜索或复核目标列。",
            "action": "先人工确认目标列和指标，再增加候选模型/搜索轮次后重跑训练验证阶段。",
            "detail": "模型效果未达到简单对照改善门槛。",
            "changed_config": {"rerun_from_stage": "training_validation", "increase_candidate_models": True},
        }
    if task.last_run and any(gate.get("id") == "leakage_review" for gate in warnings):
        return {
            "status": "proposed",
            "reason_code": "leakage_review",
            "hypothesis": "指标异常高可能来自泄漏字段，移除疑似字段后应重新验证。",
            "action": "人工确认可疑特征，必要时删除泄漏列并从数据分析阶段重跑。",
            "detail": next((gate.get("detail") for gate in warnings if gate.get("id") == "leakage_review"), ""),
            "changed_config": {"rerun_from_stage": "data_analysis", "review_leakage_columns": True},
        }
    if task.last_run and len(task.last_run.leaderboard or []) < 2:
        return {
            "status": "proposed",
            "reason_code": "candidate_models",
            "hypothesis": "候选模型太少，模型选择稳定性不足。",
            "action": "增加候选模型数量或运行轮次后重新训练验证。",
            "detail": "候选模型对比不足 2 个。",
            "changed_config": {"rerun_from_stage": "training_validation", "min_candidate_models": 3},
        }
    return {
        "status": "not_needed" if task.last_run else "pending",
        "reason_code": None,
        "hypothesis": "当前没有必须立即优化的问题。",
        "action": "进入报告生成和人工验收。",
        "detail": "如果业务目标更高，可手动发起下一轮调优。",
        "changed_config": {},
    }


def _build_stop_conditions(attempts: Any) -> dict[str, Any]:
    normalized = _normalize_attempts(attempts)
    model_attempts = [item for item in normalized if item.get("kind") == "model_run"]
    failed_attempts = [item for item in normalized[-3:] if item.get("status") in {"failed", "needs_improvement"}]
    return {
        "max_attempts": 5,
        "min_relative_improvement": 0.01,
        "max_consecutive_failed_or_unhelpful_attempts": 2,
        "current_model_attempts": len(model_attempts),
        "recent_failed_or_unhelpful_attempts": len(failed_attempts),
        "should_stop": len(model_attempts) >= 5 or len(failed_attempts) >= 2,
    }


def _build_workflow(task: TaskRecord, loop: dict[str, Any]) -> list[dict[str, Any]]:
    checklist = loop.get("checklist") if isinstance(loop.get("checklist"), list) else []
    baseline = loop.get("baseline") if isinstance(loop.get("baseline"), dict) else {}
    quality_gates = loop.get("quality_gates") if isinstance(loop.get("quality_gates"), list) else []
    next_improvement = loop.get("next_improvement") if isinstance(loop.get("next_improvement"), dict) else {}
    checklist_blocked = any(item.get("status") == "blocked" for item in checklist)
    return [
        _workflow_step("requirement_reading", "需求理解", "completed" if task.description else "pending", "读取任务名称、业务描述和 CSV 上下文。"),
        _workflow_step("task_checklist", "任务检查清单", "blocked" if checklist_blocked else "completed" if checklist else "pending", "确认数据、目标列、问题类型、指标和基础风险。"),
        _workflow_step("data_profiling", "数据体检", "completed" if task.dataset_profile else "pending", _profile_summary(task.dataset_profile)),
        _workflow_step("baseline", "简单对照测试", baseline.get("status", "pending"), baseline.get("detail") or _metric_detail(baseline)),
        _workflow_step(
            "modeling",
            "自动建模",
            "completed" if task.last_run else "running" if task.status == TaskStatus.running else "failed" if task.status == TaskStatus.failed else "pending",
            _modeling_detail(task),
        ),
        _workflow_step(
            "quality_review",
            "结果校验",
            _quality_status(quality_gates),
            _quality_detail(quality_gates),
        ),
        _workflow_step(
            "iterative_tuning",
            "反复优化",
            "proposed" if next_improvement.get("status") in {"proposed", "needs_human_or_retry"} else "completed" if task.last_run else "pending",
            next_improvement.get("action") or "等待模型结果后决定是否需要下一轮优化。",
        ),
        _workflow_step("final_report", "报告交付", "completed" if task.last_run else "pending", "基于真实结果文件生成报告，不用演示值补齐。"),
    ]


def _workflow_step(key: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _quality_status(gates: list[dict[str, Any]]) -> str:
    if not gates:
        return "pending"
    if any(gate.get("status") == "blocked" for gate in gates):
        return "blocked"
    if any(gate.get("status") == "warning" for gate in gates):
        return "warning"
    return "completed"


def _quality_detail(gates: list[dict[str, Any]]) -> str:
    if not gates:
        return "等待简单对照和模型结果。"
    warning = next((gate for gate in gates if gate.get("status") in {"blocked", "warning"}), None)
    if warning:
        return str(warning.get("detail") or warning.get("title") or "存在待确认项。")
    return "结果检查均已通过。"


def _modeling_detail(task: TaskRecord) -> str:
    if task.last_run:
        return f"{task.last_run.best_model}: {task.last_run.metric_name}={task.last_run.metric_value:.6g}"
    if task.last_run_attempt and task.last_run_attempt.diagnosis_detail:
        return task.last_run_attempt.diagnosis_detail
    if task.status == TaskStatus.running:
        return "自动建模正在运行。"
    return "等待自动建模。"


def _metric_detail(payload: dict[str, Any]) -> str:
    if not _baseline_completed(payload):
        return str(payload.get("detail") or "等待计算。")
    return f"{payload.get('label')}: {payload.get('metric_name')}={float(payload.get('metric_value')):.6g}"


def _metric_snapshot(payload: Any) -> dict[str, Any] | None:
    if not _baseline_completed(payload):
        return None
    return {
        "metric_name": payload.get("metric_name"),
        "metric_value": payload.get("metric_value"),
        "validation_score": payload.get("validation_score"),
    }


def _run_attempt_note(comparison: dict[str, Any] | None) -> str:
    if comparison is None:
        return "模型结果已记录；由于指标口径不同，暂不和简单对照直接比较。"
    if comparison["better"]:
        return f"模型超过简单对照，相对改善 {comparison['relative_delta']:.1%}。"
    return f"模型没有超过简单对照，相对变化 {comparison['relative_delta']:.1%}，建议进入优化或人工复核。"


def _compare_metric(
    model_metric_name: str,
    model_value: float,
    baseline_metric_name: str,
    baseline_value: float,
) -> dict[str, Any] | None:
    model_key = _normalize_metric(model_metric_name)
    baseline_key = _normalize_metric(baseline_metric_name)
    if model_key != baseline_key:
        return None
    lower_better = _is_lower_better(model_key)
    if lower_better:
        delta = baseline_value - model_value
        denominator = abs(baseline_value) if abs(baseline_value) > 1e-12 else 1.0
        better = delta > max(denominator * 0.01, 1e-12)
    else:
        delta = model_value - baseline_value
        denominator = abs(baseline_value) if abs(baseline_value) > 1e-12 else 1.0
        better = delta > max(denominator * 0.01, 1e-12)
    return {
        "model_value": model_value,
        "baseline_value": baseline_value,
        "delta": delta,
        "relative_delta": delta / denominator,
        "better": better,
        "direction": "lower" if lower_better else "higher",
    }


def _validation_score(metric_name: str, value: float) -> float:
    return -value if _is_lower_better(metric_name) else value


def _is_lower_better(metric_name: str) -> bool:
    return _normalize_metric(metric_name) in LOWER_IS_BETTER_METRICS


def _normalize_metric(metric_name: str | None) -> str:
    return str(metric_name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_attempts(raw_attempts: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_attempts, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_attempts):
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        payload["attempt_index"] = int(payload.get("attempt_index", index))
        normalized.append(payload)
    return normalized[-20:]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
