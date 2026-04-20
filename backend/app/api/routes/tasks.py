from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.models.task import (
    TaskCreateRequest,
    TaskListResponse,
    TaskRecord,
    TaskRunRequest,
    TaskStatus,
    TokenUsageResponse,
)
from backend.app.services.executors.base import BaseExecutor
from backend.app.services.executors.mlzero_executor import MLZeroExecutor
from backend.app.services.task_store import TaskStore
from backend.app.services.token_usage import read_token_usage


router = APIRouter(prefix="/tasks", tags=["tasks"])


@lru_cache
def get_task_store() -> TaskStore:
    settings = get_settings()
    return TaskStore(settings.storage_dir)


@lru_cache
def get_executor() -> BaseExecutor:
    return MLZeroExecutor(get_settings())


@router.get("", response_model=TaskListResponse)
def list_tasks() -> TaskListResponse:
    return TaskListResponse(items=get_task_store().list_tasks())


@router.post("", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreateRequest) -> TaskRecord:
    return get_task_store().create_task(payload)


@router.get("/{task_id}", response_model=TaskRecord)
def get_task(task_id: str) -> TaskRecord:
    task = get_task_store().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task


@router.get("/{task_id}/token-usage", response_model=TokenUsageResponse)
def get_task_token_usage(task_id: str) -> TokenUsageResponse:
    task = get_task_store().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.last_run is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task has not been run")

    output_dir = Path(task.last_run.output_dir)
    if not output_dir.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run output directory not found")

    stats = read_token_usage(output_dir)
    return TokenUsageResponse(
        task_id=task.id,
        run_output_dir=str(output_dir),
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        total_tokens=stats.total_tokens,
        source=stats.source,
        updated_at=datetime.now(timezone.utc),
    )


@router.post("/{task_id}/dataset", response_model=TaskRecord)
async def upload_dataset(task_id: str, file: UploadFile = File(...)) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only CSV uploads are supported")

    content = await file.read()
    dataset_path = task_store.save_dataset(task_id, file.filename, content)
    task.dataset_filename = file.filename
    task.dataset_path = str(dataset_path)
    task.status = TaskStatus.uploaded
    task.notes = "Dataset uploaded. Ready for an MLZero validation run."
    return task_store.save_task(task)


@router.post("/{task_id}/run", response_model=TaskRecord)
def run_task(task_id: str, payload: TaskRunRequest) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if not task.dataset_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset has not been uploaded")

    task.status = TaskStatus.running
    task.notes = "MLZero run in progress."
    task_store.save_task(task)

    try:
        summary = get_executor().run(task, Path(task.dataset_path), payload.time_limit)
    except Exception as exc:  # noqa: BLE001
        task.status = TaskStatus.failed
        task.notes = str(exc)
        task_store.save_task(task)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    task.status = TaskStatus.completed
    task.notes = "MLZero run completed."
    task.last_run = summary
    return task_store.save_task(task)
