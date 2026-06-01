from __future__ import annotations

from pathlib import Path
from typing import Iterable

from backend.app.models.task import TaskRecord


class TaskStoreStorageMixin:
    def save_dataset(self, team_id: str, task_id: str, filename: str, content: bytes) -> Path:
        return self.local_storage.save_dataset(team_id, task_id, filename, content)

    def save_dataset_chunks(self, team_id: str, task_id: str, filename: str, chunks: Iterable[bytes]) -> Path:
        return self.local_storage.save_dataset_chunks(team_id, task_id, filename, chunks)

    def dataset_upload_path(self, team_id: str, task_id: str, filename: str) -> Path:
        return self.local_storage.dataset_upload_path(team_id, task_id, filename)

    def dataset_upload_dir(self, team_id: str, task_id: str) -> Path:
        return self.local_storage.dataset_upload_dir(team_id, task_id)

    def clear_dataset_upload_dir(self, team_id: str, task_id: str) -> Path:
        return self.local_storage.clear_dataset_upload_dir(team_id, task_id)

    def _task_dir(self, team_id: str, task_id: str) -> Path:
        return self.local_storage.task_dir(team_id, task_id)

    def task_storage_uri(self, task_id: str) -> str:
        return self.local_storage.task_storage_uri(task_id)

    def run_storage_uri(self, task_id: str, run_id: str) -> str:
        return self.local_storage.run_storage_uri(task_id, run_id)

    def _write_task_manifest(self, task: TaskRecord) -> None:
        self.local_storage.write_task_manifest(task)
