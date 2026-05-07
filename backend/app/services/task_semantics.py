from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import TaskRecord, TaskSemanticUpdateRequest, TaskStatus
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_to_plain
from backend.app.services.task_human_context import ensure_task_human_loop


def apply_human_semantic_update(
    task: TaskRecord,
    payload: TaskSemanticUpdateRequest,
    *,
    corrected_by: str,
) -> TaskRecord:
    if not task.dataset_path:
        raise ValueError("请先上传 CSV 数据集，再修正任务语义。")

    dataset_path = Path(task.dataset_path)
    if not dataset_path.exists() or not dataset_path.is_file():
        raise ValueError(f"任务数据集文件不存在，无法校验目标列：{dataset_path}")

    label_column = payload.label_column.strip()
    metric_name = payload.metric_name.strip().lower()
    if not metric_name:
        raise ValueError("评估指标不能为空。")

    base_profile = task.dataset_profile or build_dataset_profile(
        dataset_path,
        filename=task.dataset_filename,
        target_column=None,
    )
    column_names = [column.name for column in base_profile.columns]
    if label_column not in column_names:
        raise ValueError(
            "人工修正的目标列不在 CSV 表头中。"
            f" 修正值：{label_column}；可选列：{', '.join(column_names)}"
        )

    now = datetime.now(timezone.utc)
    existing_requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    correction_history = _normalize_correction_history(existing_requirements.get("semantic_correction_history"))
    correction_history.append(
        {
            "corrected_at": now.isoformat(),
            "corrected_by": corrected_by,
            "previous_label_column": task.label_column,
            "previous_problem_type": task.problem_type,
            "previous_metric_name": existing_requirements.get("metric_name"),
            "previous_analysis_source": existing_requirements.get("analysis_source"),
            "previous_analyzed_at": existing_requirements.get("analyzed_at"),
            "correction_note": payload.correction_note,
        }
    )

    updated_profile = build_dataset_profile(
        dataset_path,
        filename=task.dataset_filename,
        target_column=label_column,
    )
    task.dataset_profile = updated_profile
    task.label_column = label_column
    task.problem_type = payload.problem_type
    task.last_run = None
    task.last_run_attempt = None
    task.status = TaskStatus.planning
    task.notes = (
        f"任务语义已人工修正：目标列 {label_column}，"
        f"任务类型 {payload.problem_type}，指标 {metric_name}。请重新运行 MLZero。"
    )

    human_loop = ensure_task_human_loop(task)
    human_loop["rerun_requested"] = False
    human_loop["semantic_corrected_at"] = now.isoformat()
    human_loop["semantic_corrected_by"] = corrected_by

    existing_requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    existing_requirements.update(
        {
            "analysis_source": "human_correction",
            "analysis_model": None,
            "metric_name": metric_name,
            "reasoning": payload.correction_note or "用户已人工确认目标列、任务类型和评估指标。",
            "confidence": 1.0,
            "column_names": column_names,
            "preview_rows": updated_profile.preview_rows,
            "analyzed_at": now.isoformat(),
            "corrected_at": now.isoformat(),
            "corrected_by": corrected_by,
            "correction_note": payload.correction_note,
            "analysis_prompt": None,
            "raw_response": None,
            "token_usage_calculation_method": "human_correction_no_token_usage",
            "dataset_profile": dataset_profile_to_plain(updated_profile),
            "semantic_correction_history": correction_history[-20:],
        }
    )
    task.structured_requirements = existing_requirements
    return task


def _normalize_correction_history(raw_history: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_history, list):
        return []
    return [dict(item) for item in raw_history if isinstance(item, dict)]
