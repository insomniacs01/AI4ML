from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.models.task import (
    DatasetProfile,
    TaskModelReportResponse,
    TaskRecord,
)
from backend.app.services.codex_backend import build_codex_overview_from_workspace, resolve_codex_workspace
from backend.app.services.codex_workspace_resolution import resolve_known_codex_workspace_path
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_from_plain
from backend.app.services.task_agent_loop import refresh_agent_loop_after_analysis, refresh_agent_loop_after_run
from backend.app.services.task_report_features import (
    collect_feature_importance,
    codex_feature_importance,
    parse_feature_importance_file,
)
from backend.app.services.task_report_codex_summary import codex_result_summary
from backend.app.services.task_report_notes import (
    build_data_quality_notes,
    build_limitation_notes,
    build_result_summary,
)
from backend.app.services.task_report_relationships import collect_feature_relationships
from backend.app.services.task_report_sections import (
    build_report_markdown as _build_report_markdown,
)


def build_codex_task_model_report(
    task: TaskRecord,
    *,
    resolve_dataset_from_file: bool = True,
    resolve_workspace_by_scan: bool = True,
) -> TaskModelReportResponse | None:
    workspace = _codex_workspace_path(task, resolve_by_scan=resolve_workspace_by_scan)
    if workspace is None:
        return None
    report_path = workspace / "output" / "report.md"
    metrics_path = workspace / "output" / "metrics.json"
    if not report_path.is_file():
        return None
    markdown = report_path.read_text(encoding="utf-8", errors="replace")
    metrics = _read_json_file(metrics_path)
    dataset_profile = _resolve_dataset_profile(task, resolve_from_file=resolve_dataset_from_file)
    feature_importance = codex_feature_importance(metrics, source=str(metrics_path))
    if not feature_importance:
        feature_importance = parse_feature_importance_file(workspace / "output" / "feature_importance.json")
    overview = build_codex_overview_from_workspace(workspace)
    generated_at = datetime.now(timezone.utc)
    result_summary = codex_result_summary(task, metrics)
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
    codex_report = build_codex_task_model_report(task)
    if codex_report is not None:
        return codex_report
    dataset_profile = _resolve_dataset_profile(task)
    if dataset_profile is not None and task.dataset_profile is None:
        task.dataset_profile = dataset_profile
    _ensure_agent_loop_for_report(task)
    artifact_feature_importance, feature_paths = collect_feature_importance(task)
    relationship_importance, relationship_notes = collect_feature_relationships(task, dataset_profile)
    feature_importance = artifact_feature_importance or relationship_importance
    result_summary = build_result_summary(
        task,
        feature_importance=feature_importance,
        relationship_notes=relationship_notes,
        using_artifact_importance=bool(artifact_feature_importance),
    )
    data_quality_notes = build_data_quality_notes(dataset_profile)
    limitation_notes = build_limitation_notes(
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


def _codex_workspace_path(task: TaskRecord, *, resolve_by_scan: bool = True) -> Path | None:
    settings = get_settings()
    if resolve_by_scan:
        return resolve_codex_workspace(task, settings)
    return resolve_known_codex_workspace_path(task, settings)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_dataset_profile(task: TaskRecord, *, resolve_from_file: bool = True) -> DatasetProfile | None:
    if task.dataset_profile is not None:
        return task.dataset_profile
    structured = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    cached = dataset_profile_from_plain(structured.get("dataset_profile"))
    if cached is not None:
        return cached
    if not resolve_from_file or not task.dataset_path:
        return None
    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists() or not dataset_path.is_file() or dataset_path.suffix.lower() != ".csv":
        return None
    return build_dataset_profile(
        dataset_path,
        filename=task.dataset_filename,
        target_column=task.label_column,
    )


def _ensure_agent_loop_for_report(task: TaskRecord) -> None:
    requirements = task.structured_requirements if isinstance(task.structured_requirements, dict) else {}
    if isinstance(requirements.get("agent_loop"), dict):
        return
    if task.last_run:
        refresh_agent_loop_after_run(task)
    else:
        refresh_agent_loop_after_analysis(task)
