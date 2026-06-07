from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetProfile, TaskRecord, TaskSemanticUpdateRequest, TaskStatus
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_to_plain
from backend.app.services.task_agent_loop import refresh_agent_loop_after_analysis
from backend.app.services.task_human_context import ensure_task_human_loop
from backend.app.services.task_targets import split_target_columns
from backend.app.services.task_uploads import is_csv_upload_filename


def apply_human_semantic_update(
    task: TaskRecord,
    payload: TaskSemanticUpdateRequest,
    *,
    corrected_by: str,
) -> TaskRecord:
    dataset_path = _require_existing_dataset_path(task)
    label_column, metric_name = _semantic_values(payload)
    base_profile = _base_profile_for_semantic_update(task, dataset_path)
    column_names = _column_names(base_profile)
    target_columns = split_target_columns(label_column)
    _validate_target_columns(target_columns, column_names)

    now = datetime.now(timezone.utc)
    existing_requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    correction_history = _semantic_correction_history(task, existing_requirements, payload, corrected_by, now)

    updated_profile = _updated_profile_for_semantic_update(
        task,
        dataset_path,
        base_profile,
        label_column=label_column,
        target_columns=target_columns,
    )
    _apply_semantic_task_state(task, payload, label_column=label_column, metric_name=metric_name, updated_profile=updated_profile)

    human_loop = ensure_task_human_loop(task)
    human_loop["rerun_requested"] = False
    human_loop["semantic_corrected_at"] = now.isoformat()
    human_loop["semantic_corrected_by"] = corrected_by

    task.structured_requirements = _semantic_requirements(
        task,
        payload,
        metric_name=metric_name,
        column_names=column_names,
        target_columns=target_columns,
        updated_profile=updated_profile,
        correction_history=correction_history,
        corrected_by=corrected_by,
        corrected_at=now,
    )
    refresh_agent_loop_after_analysis(task)
    return task


def _require_existing_dataset_path(task: TaskRecord) -> Path:
    if not task.dataset_path:
        raise ValueError("请先上传数据集，再修正任务语义。")
    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists():
        raise ValueError(f"任务数据集文件不存在，无法校验目标列：{dataset_path}")
    return dataset_path


def _semantic_values(payload: TaskSemanticUpdateRequest) -> tuple[str, str]:
    label_column = payload.label_column.strip()
    metric_name = payload.metric_name.strip().lower()
    if not metric_name:
        raise ValueError("评估指标不能为空。")
    return label_column, metric_name


def _base_profile_for_semantic_update(task: TaskRecord, dataset_path: Path) -> DatasetProfile | None:
    if task.dataset_profile is not None:
        return task.dataset_profile
    if dataset_path.is_file() and is_csv_upload_filename(dataset_path.name):
        return build_dataset_profile(
            dataset_path,
            filename=task.dataset_filename,
            target_column=None,
        )
    return None


def _column_names(profile: DatasetProfile | None) -> list[str]:
    return [column.name for column in profile.columns] if profile is not None else []


def _validate_target_columns(target_columns: list[str], column_names: list[str]) -> None:
    unknown_columns = [column for column in target_columns if column not in column_names]
    if column_names and unknown_columns:
        raise ValueError(
            "人工修正的目标列不在数据表头中。"
            f" 修正值：{', '.join(unknown_columns)}；可选列：{', '.join(column_names)}"
        )


def _semantic_correction_history(
    task: TaskRecord,
    requirements: dict[str, Any],
    payload: TaskSemanticUpdateRequest,
    corrected_by: str,
    corrected_at: datetime,
) -> list[dict[str, Any]]:
    correction_history = _normalize_correction_history(requirements.get("semantic_correction_history"))
    correction_history.append(
        {
            "corrected_at": corrected_at.isoformat(),
            "corrected_by": corrected_by,
            "previous_label_column": task.label_column,
            "previous_problem_type": task.problem_type,
            "previous_metric_name": requirements.get("metric_name"),
            "previous_analysis_source": requirements.get("analysis_source"),
            "previous_analyzed_at": requirements.get("analyzed_at"),
            "correction_note": payload.correction_note,
        }
    )
    return correction_history


def _updated_profile_for_semantic_update(
    task: TaskRecord,
    dataset_path: Path,
    base_profile: DatasetProfile | None,
    *,
    label_column: str,
    target_columns: list[str],
) -> DatasetProfile | None:
    if dataset_path.is_file() and is_csv_upload_filename(dataset_path.name) and len(target_columns) <= 1:
        return build_dataset_profile(
            dataset_path,
            filename=task.dataset_filename,
            target_column=label_column,
        )
    if base_profile is not None:
        return base_profile.model_copy(update={"target_column": label_column})
    return None


def _apply_semantic_task_state(
    task: TaskRecord,
    payload: TaskSemanticUpdateRequest,
    *,
    label_column: str,
    metric_name: str,
    updated_profile: DatasetProfile | None,
) -> None:
    task.dataset_profile = updated_profile
    task.label_column = label_column
    task.problem_type = payload.problem_type
    task.last_run = None
    task.last_run_attempt = None
    task.status = TaskStatus.planning
    task.notes = (
        f"任务语义已人工修正：目标列 {label_column}，"
        f"任务类型 {payload.problem_type}，指标 {metric_name}。请重新运行 Codex。"
    )


def _semantic_requirements(
    task: TaskRecord,
    payload: TaskSemanticUpdateRequest,
    *,
    metric_name: str,
    column_names: list[str],
    target_columns: list[str],
    updated_profile: DatasetProfile | None,
    correction_history: list[dict[str, Any]],
    corrected_by: str,
    corrected_at: datetime,
) -> dict[str, Any]:
    requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    requirements.update(
        {
            "analysis_source": "human_correction",
            "analysis_model": None,
            "metric_name": metric_name,
            "reasoning": payload.correction_note or "用户已人工确认目标列、任务类型和评估指标。",
            "confidence": 1.0,
            "column_names": column_names,
            "preview_rows": updated_profile.preview_rows if updated_profile is not None else [],
            "analyzed_at": corrected_at.isoformat(),
            "corrected_at": corrected_at.isoformat(),
            "corrected_by": corrected_by,
            "correction_note": payload.correction_note,
            "analysis_prompt": None,
            "raw_response": None,
            "token_usage_calculation_method": "human_correction_no_token_usage",
            "semantic_correction_history": correction_history[-20:],
        }
    )
    if updated_profile is not None:
        requirements["dataset_profile"] = dataset_profile_to_plain(updated_profile)
    else:
        requirements.pop("dataset_profile", None)
    if target_columns:
        requirements["target_columns"] = target_columns
        requirements["target_definition"] = {
            "target_mode": "multi_target" if len(target_columns) > 1 else "single_target",
            "target_columns": target_columns,
            "source": "human_correction",
        }
    return requirements


def _normalize_correction_history(raw_history: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_history, list):
        return []
    return [dict(item) for item in raw_history if isinstance(item, dict)]
