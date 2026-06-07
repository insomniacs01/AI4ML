from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.models.task import DatasetProfile, TaskRecord, TaskStatus
from backend.app.services.dataset_profile import dataset_profile_to_plain
from backend.app.services.task_targets import split_target_columns, target_columns_from_requirements


def apply_uploaded_dataset_to_task(
    task: TaskRecord,
    *,
    filename: str,
    dataset_dir: Path,
    uploaded_file_path: Path,
    size_bytes: int,
    content_type: str | None,
    dataset_profile: DatasetProfile | None,
    profile_error: str,
) -> TaskRecord:
    _reset_task_for_uploaded_dataset(
        task,
        filename=filename,
        dataset_dir=dataset_dir,
        dataset_profile=dataset_profile,
    )
    task.structured_requirements = _uploaded_dataset_requirements(
        task,
        filename=filename,
        dataset_dir=dataset_dir,
        uploaded_file_path=uploaded_file_path,
        size_bytes=size_bytes,
        content_type=content_type,
        dataset_profile=dataset_profile,
        profile_error=profile_error,
    )
    return task


def _reset_task_for_uploaded_dataset(
    task: TaskRecord,
    *,
    filename: str,
    dataset_dir: Path,
    dataset_profile: DatasetProfile | None,
) -> None:
    task.dataset_filename = filename
    task.dataset_path = str(dataset_dir)
    task.dataset_profile = dataset_profile
    task.status = TaskStatus.uploaded
    task.executor_type = "codex"
    task.codex_workspace_path = None
    task.codex_session_id = None
    task.codex_thread_id = None
    task.codex_status = None
    task.codex_started_at = None
    task.codex_finished_at = None
    task.last_run = None
    task.last_run_attempt = None
    task.analysis_token_usage = None


def _uploaded_dataset_requirements(
    task: TaskRecord,
    *,
    filename: str,
    dataset_dir: Path,
    uploaded_file_path: Path,
    size_bytes: int,
    content_type: str | None,
    dataset_profile: DatasetProfile | None,
    profile_error: str,
) -> dict[str, Any]:
    structured_requirements = (
        dict(task.structured_requirements)
        if isinstance(task.structured_requirements, dict)
        else {}
    )
    structured_requirements["dataset_input"] = {
        "path": str(dataset_dir),
        "path_type": "directory",
        "files": [
            {
                "filename": filename,
                "path": str(uploaded_file_path),
                "size_bytes": size_bytes,
                "content_type": content_type,
            }
        ],
    }
    structured_requirements["dataset_files"] = structured_requirements["dataset_input"]["files"]
    if dataset_profile is not None:
        structured_requirements["dataset_profile"] = dataset_profile_to_plain(dataset_profile)
        structured_requirements.pop("dataset_profile_error", None)
    else:
        structured_requirements.pop("dataset_profile", None)
        if profile_error:
            structured_requirements["dataset_profile_error"] = profile_error
    _apply_target_hints(structured_requirements, task)
    return structured_requirements


def _apply_target_hints(structured_requirements: dict[str, Any], task: TaskRecord) -> None:
    target_columns = target_columns_from_requirements(structured_requirements) or split_target_columns(task.label_column)
    if target_columns:
        structured_requirements["target_hint"] = structured_requirements.get("target_hint") or task.label_column
        structured_requirements["target_columns_hint"] = target_columns
        structured_requirements["target_definition"] = {
            "target_mode": "multi_target" if len(target_columns) > 1 else "single_target",
            "target_columns": target_columns,
            "source": "user_input",
        }
