from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.models.task import (
    DatasetProfile,
    FeatureImportanceEntry,
    TaskModelReportResponse,
    TaskRecord,
)
from backend.app.services.codex_backend import build_codex_overview_from_workspace, resolve_codex_workspace
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_from_plain
from backend.app.services.task_agent_loop import refresh_agent_loop_after_analysis, refresh_agent_loop_after_run
from backend.app.services.task_report_features import collect_feature_importance, codex_feature_importance
from backend.app.services.task_report_formatting import (
    coerce_float as _coerce_float,
    format_metric_value as _format_metric_value,
)
from backend.app.services.task_report_relationships import collect_feature_relationships
from backend.app.services.task_report_sections import (
    build_report_markdown as _build_report_markdown,
    format_top_features as _format_top_features,
)


def _build_codex_model_report(task: TaskRecord) -> TaskModelReportResponse | None:
    workspace = _codex_workspace_path(task)
    if workspace is None:
        return None
    report_path = workspace / "output" / "report.md"
    metrics_path = workspace / "output" / "metrics.json"
    if not report_path.is_file():
        return None
    markdown = report_path.read_text(encoding="utf-8", errors="replace")
    metrics = _read_json_file(metrics_path)
    dataset_profile = _resolve_dataset_profile(task)
    feature_importance = codex_feature_importance(metrics, source=str(metrics_path))
    overview = build_codex_overview_from_workspace(workspace)
    generated_at = datetime.now(timezone.utc)
    result_summary = _codex_result_summary(task, metrics)
    return TaskModelReportResponse(
        task_id=task.id,
        task_name=task.name,
        generated_at=generated_at,
        dataset_profile=dataset_profile,
        feature_importance=feature_importance,
        result_summary=result_summary,
        data_quality_notes=[],
        relationship_notes=[],
        limitation_notes=[],
        overview=overview,
        artifact_paths=[
            str(path)
            for path in [metrics_path, workspace / "output" / "overview.json", report_path]
            if path.exists()
        ],
        report_markdown=markdown,
    )


def build_task_model_report(task: TaskRecord) -> TaskModelReportResponse:
    codex_report = _build_codex_model_report(task)
    if codex_report is not None:
        return codex_report
    dataset_profile = _resolve_dataset_profile(task)
    if dataset_profile is not None and task.dataset_profile is None:
        task.dataset_profile = dataset_profile
    _ensure_agent_loop_for_report(task)
    artifact_feature_importance, feature_paths = collect_feature_importance(task)
    relationship_importance, relationship_notes = collect_feature_relationships(task, dataset_profile)
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
        overview={},
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


def _codex_workspace_path(task: TaskRecord) -> Path | None:
    return resolve_codex_workspace(task, get_settings())


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _codex_result_summary(task: TaskRecord, metrics: dict[str, Any]) -> list[str]:
    selected = metrics.get("selected_model") if isinstance(metrics.get("selected_model"), dict) else {}
    metric_name, metric_value = _codex_summary_metric(task, selected)
    lines = []
    best_model = _codex_summary_best_model(task, selected)
    if best_model:
        lines.append(f"最佳模型：{best_model}")
    if metric_name:
        lines.append(f"评价指标：{metric_name} = {_format_metric_value(metric_value)}")
    rationale = _codex_summary_rationale(selected)
    if rationale:
        lines.append(rationale)
    return lines


def _codex_summary_metric(task: TaskRecord, selected: dict[str, Any]) -> tuple[str, float | None]:
    if task.last_run:
        return task.last_run.metric_name, task.last_run.metric_value
    return _selected_model_metric(selected)


def _selected_model_metric(selected: dict[str, Any]) -> tuple[str, float | None]:
    for container_name in ("cross_validation", "holdout"):
        metric_name, metric_value = _metric_from_container(selected.get(container_name))
        if metric_name:
            return metric_name, metric_value
    return "", None


def _metric_from_container(container: Any) -> tuple[str, float | None]:
    if not isinstance(container, dict):
        return "", None
    for candidate in ("macro_f1_mean", "accuracy_mean", "macro_f1", "accuracy", "r2", "rmse", "mae"):
        value = _coerce_float(container.get(candidate))
        if value is not None:
            return candidate, value
    return "", None


def _codex_summary_best_model(task: TaskRecord, selected: dict[str, Any]) -> str | None:
    selected_name = selected.get("name")
    if isinstance(selected_name, str):
        return selected_name
    return task.last_run.best_model if task.last_run else None


def _codex_summary_rationale(selected: dict[str, Any]) -> str:
    rationale = selected.get("selection_rationale")
    return rationale.strip() if isinstance(rationale, str) and rationale.strip() else ""


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


def _ensure_agent_loop_for_report(task: TaskRecord) -> None:
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    if isinstance(requirements.get("agent_loop"), dict):
        return
    if task.last_run:
        refresh_agent_loop_after_run(task)
    else:
        refresh_agent_loop_after_analysis(task)
