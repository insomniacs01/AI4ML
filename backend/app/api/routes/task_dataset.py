from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import DatasetProfile, TaskRecord, TaskRunRequest, WorkflowStage, WorkflowStageStatus
from backend.app.services.dataset_profile import build_dataset_profile
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_agent_loop import initialize_agent_loop_for_upload
from backend.app.services.task_dataset_upload_state import apply_uploaded_dataset_to_task
from backend.app.services.task_uploads import (
    CSV_UPLOAD_CHUNK_BYTES,
    MAX_DATASET_UPLOAD_BYTES,
    is_csv_upload_filename as _is_csv_upload_filename,
    validate_csv_sample as _validate_csv_sample,
    validate_upload_content_type as _validate_upload_content_type,
    validate_upload_filename as _validate_upload_filename,
)
from backend.app.services.task_workflow_tracking import _record_workflow_stage
from backend.app.api.routes.task_run import run_task


router = APIRouter(tags=["task-lifecycle"])


@router.post("/{task_id}/dataset", response_model=TaskRecord)
async def upload_dataset(
    task_id: str,
    auto_run: bool = Query(default=True),
    time_limit: int | None = Query(default=None, ge=5, le=300),
    file: UploadFile = File(...),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    filename = _validate_upload_filename(file.filename or "")
    _validate_upload_content_type(file.content_type)

    dataset_dir = task_store.clear_dataset_upload_dir(team_access.team_id, task_id)
    uploaded_file_path = task_store.dataset_upload_path(team_access.team_id, task_id, filename)
    size_bytes, dataset_profile, profile_error = await _save_uploaded_dataset_file(
        file,
        filename=filename,
        uploaded_file_path=uploaded_file_path,
    )
    task = apply_uploaded_dataset_to_task(
        task,
        filename=filename,
        dataset_dir=dataset_dir,
        uploaded_file_path=uploaded_file_path,
        size_bytes=size_bytes,
        content_type=file.content_type,
        dataset_profile=dataset_profile,
        profile_error=profile_error,
    )
    initialize_agent_loop_for_upload(task)
    task.notes = "数据文件已上传到任务数据目录，Codex 将读取目录内容并生成建模计划。"
    task = task_store.save_task(task, access_token=team_access.access_token)
    _record_dataset_upload_stage(
        task,
        team_access,
        filename=filename,
        dataset_dir=dataset_dir,
        uploaded_file_path=uploaded_file_path,
        size_bytes=size_bytes,
        dataset_profile=dataset_profile,
    )

    if not auto_run:
        return task
    return run_task(
        task.id,
        TaskRunRequest(time_limit=time_limit),
        team_access,
    )


async def _save_uploaded_dataset_file(
    file: UploadFile,
    *,
    filename: str,
    uploaded_file_path: Path,
) -> tuple[int, DatasetProfile | None, str]:
    size_bytes = 0
    sample = bytearray()
    dataset_profile = None
    profile_error = ""
    try:
        with uploaded_file_path.open("wb") as handle:
            while True:
                chunk = await file.read(CSV_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > MAX_DATASET_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"dataset upload exceeds {MAX_DATASET_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                    )
                if len(sample) < CSV_UPLOAD_CHUNK_BYTES:
                    sample.extend(chunk[: CSV_UPLOAD_CHUNK_BYTES - len(sample)])
                handle.write(chunk)
        if size_bytes == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded dataset file is empty")
        if _is_csv_upload_filename(filename):
            try:
                _validate_csv_sample(bytes(sample))
                csv_profile = build_dataset_profile(
                    uploaded_file_path,
                    filename=filename,
                    target_column=None,
                )
                if csv_profile.column_count > 0:
                    dataset_profile = csv_profile
                else:
                    profile_error = "uploaded CSV does not contain a header row"
            except HTTPException as exc:
                profile_error = str(exc.detail)
    except HTTPException:
        _delete_partial_upload(uploaded_file_path)
        raise
    except OSError as exc:
        _delete_partial_upload(uploaded_file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to save uploaded dataset: {exc}",
        ) from exc
    return size_bytes, dataset_profile, profile_error


def _delete_partial_upload(uploaded_file_path: Path) -> None:
    if uploaded_file_path.exists():
        uploaded_file_path.unlink()


def _record_dataset_upload_stage(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    filename: str,
    dataset_dir: Path,
    uploaded_file_path: Path,
    size_bytes: int,
    dataset_profile: DatasetProfile | None,
) -> None:
    _record_workflow_stage(
        task,
        team_access,
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.completed,
        summary=(
            f"数据文件已上传：{filename}，大小 {size_bytes} 字节。"
            + (
                f" CSV 画像：{dataset_profile.row_count} 行、{dataset_profile.column_count} 列。"
                if dataset_profile is not None
                else " 数据结构将由 Codex 在任务工作区内解析。"
            )
        ),
        artifact_refs=[str(uploaded_file_path), str(dataset_dir)],
        log_excerpt=(
            f"filename={filename}; size_bytes={size_bytes}; "
            + (
                f"columns={', '.join(column.name for column in dataset_profile.columns[:12])}"
                if dataset_profile is not None
                else f"dataset_dir={dataset_dir}"
            )
        ),
    )
